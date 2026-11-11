"""Contract tests for n8n-to-Publisher ingestion, without network or actual publishing."""
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import accounts, ingests, media, posts, make_engine
from app.main import create_app
from app.security import Vault, password_hash
from app.tiktok_ingest import DownloadError, validate_tiktok_url
from app.worker import process_one_ingest, process_one


class FakeProviders:
    def __init__(self):
        self.published = []

    def close(self):
        pass

    def available(self, provider):
        return provider == 'youtube'

    def refresh_youtube(self, tokens):
        return tokens

    def publish(self, account, tokens, post, file):
        self.published.append((account['id'], post['privacy'], post['id']))
        return 'video-private-test', 'https://www.youtube.com/watch?v=video-private-test'


@pytest.fixture
def automation(tmp_path):
    cfg = Settings(
        database_url=f'sqlite:///{tmp_path}/test.db',
        data_dir=tmp_path,
        base_url='http://localhost:8000',
        encryption_key=Fernet.generate_key().decode(),
        admin_password_hash=password_hash('password-for-local-testing'),
        automation_token='secure-test-service-token-' + ('a' * 40),
        automation_youtube_account_id='youtube-test-account',
        tiktok_ingest_enabled=True,
        worker_enabled=False,
    )
    cfg.validate()
    engine = make_engine(cfg.database_url)
    fake = FakeProviders()
    app = create_app(cfg, engine, fake)
    with TestClient(app, base_url=cfg.base_url) as client:
        with engine.begin() as c:
            c.execute(accounts.insert().values(
                id=cfg.automation_youtube_account_id,
                provider='youtube', external_id='channel-1', name='My channel',
                tokens=Vault(cfg.encryption_key).encrypt({'access_token': 'mock'}),
                active=True, created_at=time.time()))
        yield cfg, engine, fake, client


def headers(cfg):
    return {'Authorization': 'Bearer ' + cfg.automation_token}


def item(**changes):
    return {
        'request_key': 'telegram-chat-123-message-456',
        'telegram_chat_id': '123456789',
        'source_url': 'https://www.tiktok.com/@creator/video/7281234567890123456?utm_source=test',
        'title': 'My authorized video',
        'description': 'Test',
        'rights_confirmed': True,
        'made_for_kids': False,
        **changes,
    }


def test_tiktok_host_restrictions():
    assert validate_tiktok_url('https://www.tiktok.com/@creator/video/7281234567890123456?foo=1') == (
        'https://www.tiktok.com/@creator/video/7281234567890123456')
    assert validate_tiktok_url('https://vt.tiktok.com/ZS123ABC/') == (
        'https://vt.tiktok.com/ZS123ABC/')
    for url in [
        'https://www.tiktok.com.evil.org/@creator/video/7281234567890123456',
        'http://www.tiktok.com/@creator/video/7281234567890123456',
        'https://127.0.0.1/@creator/video/7281234567890123456',
        'https://www.tiktok.com:8080/@creator/video/7281234567890123456',
        'https://attacker@www.tiktok.com/@creator/video/7281234567890123456',
        'https://www.tiktok.com/@creator', 'file:///etc/passwd',
    ]:
        with pytest.raises(DownloadError):
            validate_tiktok_url(url)


def test_service_auth_url_validation_and_rights(automation):
    cfg, _, _, client = automation
    assert client.post('/internal/v1/tiktok', json=item()).status_code == 401
    assert client.post('/internal/v1/tiktok', headers={'Authorization': 'Bearer bad'},
                       json=item()).status_code == 401
    assert client.post('/internal/v1/tiktok', headers=headers(cfg),
                       json=item(rights_confirmed=False)).status_code == 422
    assert client.post('/internal/v1/tiktok', headers=headers(cfg),
                       json=item(source_url='https://evil.example.com/bad')).status_code == 400
    assert client.post('/internal/v1/tiktok', headers=headers(cfg),
                       json=item(scheduled_at='2030-10-10T10:00:00')).status_code == 400


def test_end_to_end_ingest_queue_publish_status_and_deduplication(automation, tmp_path):
    cfg, engine, provider, client = automation
    r = client.post('/internal/v1/tiktok', json=item(), headers=headers(cfg))
    assert r.status_code == 200
    data = r.json()
    assert data['status'] == 'pending' and not data['deduplicated']
    job_id = data['id']
    repeat = client.post('/internal/v1/tiktok', json=item(), headers=headers(cfg))
    assert repeat.status_code == 200
    assert repeat.json()['id'] == job_id and repeat.json()['deduplicated']
    changed = client.post('/internal/v1/tiktok', json=item(
        source_url='https://vt.tiktok.com/ZX9999/'), headers=headers(cfg))
    assert changed.status_code == 409

    def fake_download(settings, url):
        path = settings.data_dir / 'media' / 'sample-import.mp4'
        path.write_bytes(b'fake-mp4-not-for-production')
        return {'id': 'media-for-test', 'filename': 'sample-import.mp4',
                'path': str(path), 'size': path.stat().st_size,
                'duration': 25.0, 'width': 720, 'height': 1280,
                'created_at': time.time()}

    assert process_one_ingest(engine, cfg, downloader=fake_download)
    assert not process_one_ingest(engine, cfg, downloader=fake_download)
    ready = client.get(f'/internal/v1/tiktok/{job_id}', headers=headers(cfg)).json()
    assert ready['status'] == 'queued'
    with engine.connect() as c:
        row = c.execute(select(posts)).mappings().one()
        assert row['privacy'] == 'private' and row['shorts']
        assert c.execute(select(media)).first() is not None
        assert c.execute(select(ingests)).mappings().one()['post_id'] == row['id']

    assert process_one(engine, provider, Vault(cfg.encryption_key))
    done = client.get(f'/internal/v1/tiktok/{job_id}', headers=headers(cfg)).json()
    assert done['status'] == 'submitted' and done['terminal']
    assert done['remote_id'] == 'video-private-test'
    notifications = client.get('/internal/v1/notifications', headers=headers(cfg)).json()['notifications']
    assert len(notifications) == 1
    assert notifications[0]['chat_id'] == '123456789'
    assert notifications[0]['status'] == 'submitted'
    assert client.post(f'/internal/v1/tiktok/{job_id}/ack', headers=headers(cfg)).status_code == 200
    assert client.get('/internal/v1/notifications', headers=headers(cfg)).json()['notifications'] == []
    assert provider.published[0][1] == 'private'
    assert not process_one(engine, provider, Vault(cfg.encryption_key))


def test_failed_downloader_does_not_publish(automation):
    cfg, engine, provider, client = automation
    job_id = client.post('/internal/v1/tiktok', json=item(), headers=headers(cfg)).json()['id']
    def fail(settings, url):
        raise DownloadError('untrusted third party error includes credential')
    assert process_one_ingest(engine, cfg, downloader=fail)
    result = client.get(f'/internal/v1/tiktok/{job_id}', headers=headers(cfg)).json()
    assert result['status'] == 'failed'
    assert 'credential' not in result['error']
    assert result['terminal']
    pending = client.get('/internal/v1/notifications', headers=headers(cfg)).json()['notifications']
    assert len(pending) == 1 and pending[0]['status'] == 'failed'
    assert client.post(f'/internal/v1/tiktok/{job_id}/ack', headers=headers(cfg)).status_code == 200
    assert not process_one(engine, provider, Vault(cfg.encryption_key))


def test_scheduling_is_respected_after_ingestion(automation):
    cfg, engine, provider, client = automation
    r = client.post('/internal/v1/tiktok', json=item(
        scheduled_at='2030-10-10T10:00:00+07:00'), headers=headers(cfg))
    assert r.status_code == 200
    def fake_download(settings, url):
        path = settings.data_dir / 'media' / 'scheduled.mp4'
        path.write_bytes(b'fake')
        return {'id': 'media-future', 'filename': path.name, 'path': str(path),
                'size': 4, 'duration': 4, 'width': 1080, 'height': 1920,
                'created_at': time.time()}
    assert process_one_ingest(engine, cfg, downloader=fake_download)
    assert not process_one(engine, provider, Vault(cfg.encryption_key))


def test_ingest_disabled_rejects_service_calls(automation):
    cfg, _, _, client = automation
    cfg.tiktok_ingest_enabled = False
    assert client.post('/internal/v1/tiktok', json=item(), headers=headers(cfg)).status_code == 503
