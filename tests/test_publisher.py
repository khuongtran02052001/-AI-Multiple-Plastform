import io
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select, update, func

from app.config import Settings
from app.db import make_engine, initialize, accounts, posts, media, sessions, oauth_states, claim_post
from app.main import create_app
from app.security import password_hash, Vault
from app.providers import Providers, PublishError
from app.worker import process_one, maintenance


class FakeProviders:
    def __init__(self):
        self.calls = []
        self.fail = None

    def available(self, provider):
        return provider in ('youtube', 'facebook')

    def close(self):
        pass

    def authorize_url(self, provider, state, verifier):
        return 'https://example.org/oauth?state=' + state

    def exchange(self, provider, code, verifier):
        return [{'external_id': 'channel-1', 'name': 'My channel',
                 'tokens': {'access_token': 'private-token', 'refresh_token': 'refresh', 'expires_at': time.time()+3600}}]

    def refresh_youtube(self, tokens):
        return tokens

    def publish(self, account, tokens, post, file):
        self.calls.append(post['id'])
        if self.fail:
            raise self.fail
        return 'result-123', 'https://www.youtube.com/watch?v=result-123'


@pytest.fixture
def setup(tmp_path):
    settings = Settings(database_url=f'sqlite:///{tmp_path}/test.db', data_dir=tmp_path,
        encryption_key=Fernet.generate_key().decode(), admin_password_hash=password_hash('a-strong-test-password'),
        base_url='http://localhost:8000', worker_enabled=False)
    settings.validate()
    engine = make_engine(settings.database_url)
    fake = FakeProviders()
    app = create_app(settings, engine, fake)
    with TestClient(app, base_url=settings.base_url) as client:
        yield settings, engine, fake, client


def login(client):
    r = client.post('/api/login', json={'password': 'a-strong-test-password'},
                    headers={'Origin': 'http://localhost:8000'})
    assert r.status_code == 200
    return {'Origin': 'http://localhost:8000', 'X-CSRF-Token': r.json()['csrf']}


def account(engine, settings, provider='facebook'):
    with engine.begin() as c:
        c.execute(accounts.insert().values(id='account-1', provider=provider, external_id='page-1',
            name='Test account', tokens=Vault(settings.encryption_key).encrypt({'access_token':'secret','kind':'page'}),
            active=True, created_at=time.time()))


def payload(**changes):
    return {'batch_key': 'idempotency-key-123', 'account_ids': ['account-1'],
            'title': 'My title', 'description': 'My description', 'action': 'queue', **changes}


def test_authentication_csrf_and_logout(setup):
    _, _, _, client = setup
    assert client.get('/api/posts').status_code == 401
    assert client.post('/api/login', json={'password':'bad'}, headers={'Origin':'https://evil.test'}).status_code == 403
    headers = login(client)
    assert client.post('/api/posts', json=payload()).status_code == 403
    assert client.get('/api/session').json()['csrf'] == headers['X-CSRF-Token']
    assert client.post('/api/logout', headers=headers).status_code == 200
    assert client.get('/api/session').status_code == 401


def test_login_rate_limit(setup):
    *_, client = setup
    for _ in range(10):
        assert client.post('/api/login', json={'password':'bad'}, headers={'Origin':'http://localhost:8000'}).status_code == 401
    assert client.post('/api/login', json={'password':'bad'}, headers={'Origin':'http://localhost:8000'}).status_code == 429


def test_duplicate_submission_and_cancel(setup):
    settings, engine, _, client = setup
    headers = login(client)
    account(engine, settings)
    first = client.post('/api/posts', json=payload(), headers=headers).json()
    second = client.post('/api/posts', json=payload(), headers=headers).json()
    assert first['ids'] == second['ids']
    assert second['deduplicated'] is True
    assert len(client.get('/api/posts').json()) == 1
    assert client.post(f'/api/posts/{first["ids"][0]}/cancel', headers=headers).status_code == 200
    assert claim_post(engine) is None


def test_atomic_claim_two_workers(setup):
    settings, engine, _, client = setup
    headers = login(client); account(engine, settings)
    client.post('/api/posts', json=payload(), headers=headers)
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda _: claim_post(engine), range(2)))
    assert sum(x is not None for x in results) == 1


@pytest.mark.parametrize('error,status', [(None,'submitted'),(PublishError('Denied'),'failed'),
    (PublishError('Network timeout',uncertain=True),'unknown'),(RuntimeError('private data'),'unknown')])
def test_worker_outcomes_no_auto_retry(setup, error, status):
    settings, engine, fake, client = setup
    headers = login(client); account(engine, settings)
    post_id = client.post('/api/posts', json=payload(), headers=headers).json()['ids'][0]
    fake.fail = error
    assert process_one(engine, fake, Vault(settings.encryption_key)) is True
    result = client.get('/api/posts').json()[0]
    assert result['status'] == status
    assert 'private data' not in (result['error'] or '')
    assert process_one(engine, fake, Vault(settings.encryption_key)) is False
    assert fake.calls == [post_id]
    if status in ('submitted','unknown'):
        assert client.post(f'/api/posts/{post_id}/queue',headers=headers).status_code == 409


def test_crashed_worker_becomes_unknown(setup):
    settings, engine, _, client = setup
    headers = login(client); account(engine, settings)
    client.post('/api/posts', json=payload(), headers=headers)
    post_id = claim_post(engine)
    with engine.begin() as c:
        c.execute(update(posts).where(posts.c.id == post_id).values(lease_until=time.time()-1))
    maintenance(engine, settings)
    assert client.get('/api/posts').json()[0]['status'] == 'unknown'
    assert claim_post(engine) is None


def test_oauth_single_use_bound_to_session_and_encrypted_tokens(setup):
    settings, engine, _, client = setup
    headers = login(client)
    r = client.post('/api/oauth/youtube/start',headers=headers)
    state = r.json()['url'].split('state=')[1]
    # A different logged-in browser cannot redeem the first browser's state.
    with TestClient(client.app,base_url=settings.base_url) as other:
        login(other)
        assert other.get('/oauth/youtube/callback',params={'state':state,'code':'x'}).status_code == 400
    r = client.get('/oauth/youtube/callback',params={'state':state,'code':'x'},follow_redirects=False)
    assert r.status_code == 303
    assert client.get('/oauth/youtube/callback',params={'state':state,'code':'x'}).status_code == 400
    visible = client.get('/api/accounts').text
    assert 'private-token' not in visible and 'tokens' not in visible
    with engine.connect() as c:
        stored = c.execute(select(accounts.c.tokens)).scalar_one()
    assert 'private-token' not in stored
    assert Vault(settings.encryption_key).decrypt(stored)['access_token'] == 'private-token'


def test_disconnect_stops_queued_jobs(setup):
    settings, engine, _, client = setup
    headers = login(client); account(engine, settings)
    post_id = client.post('/api/posts', json=payload(), headers=headers).json()['ids'][0]
    assert client.post('/api/accounts/account-1/disconnect',headers=headers).status_code == 200
    assert client.get('/api/accounts').json() == []
    assert client.get('/api/posts').json()[0]['status'] == 'failed'
    assert client.post(f'/api/posts/{post_id}/queue',headers=headers).status_code == 400


def test_youtube_requires_video_and_aware_schedule(setup):
    settings, engine, _, client = setup
    headers=login(client); account(engine,settings,provider='youtube')
    assert client.post('/api/posts',json=payload(),headers=headers).status_code == 400
    assert client.post('/api/posts',json=payload(scheduled_at='2030-01-01T00:00:00'),headers=headers).status_code == 400


def test_media_validation_and_shorts(setup,tmp_path):
    settings,engine,_,client=setup
    headers=login(client);account(engine,settings,provider='youtube')
    assert client.post('/api/media',files={'file':('x.mp4',b'invalid','video/mp4')}).status_code == 403
    assert client.post('/api/media',headers=headers,files={'file':('x.mp4',b'invalid','video/mp4')}).status_code == 400
    video=tmp_path/'sample.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=green:s=160x90:d=1',
        '-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
    r=client.post('/api/media',headers=headers,files={'file':('sample.mp4',video.read_bytes(),'video/mp4')})
    assert r.status_code == 200
    data=r.json(); assert data['width']==160 and 'path' not in data
    assert client.post('/api/posts',headers=headers,json=payload(media_id=data['id'])).status_code == 400
    assert client.post('/api/posts',headers=headers,json=payload(media_id=data['id'],shorts=False)).status_code == 200


def test_youtube_real_http_contract_mocked(setup,tmp_path):
    settings,*_=setup
    settings.google_client_id='client'; settings.google_client_secret='secret'
    calls=[]
    def handler(request):
        calls.append(request)
        if request.method=='POST':
            assert json.loads(request.content)['status']['privacyStatus']=='private'
            return httpx.Response(200,headers={'Location':'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=x'})
        assert request.method=='PUT' and request.content==b'test-video'
        return httpx.Response(200,json={'id':'video-1'})
    p=Providers(settings,httpx.Client(transport=httpx.MockTransport(handler)))
    path=tmp_path/'video.mp4';path.write_bytes(b'test-video')
    result=p.publish({'provider':'youtube'},{'access_token':'token'},
        {'title':'Title','description':'Description','tags':'[]','privacy':'private','made_for_kids':False},
        {'path':str(path),'size':10})
    assert result[0]=='video-1' and len(calls)==2


def test_facebook_page_token_and_error_redaction(setup):
    settings,*_=setup
    def handler(request):
        return httpx.Response(400,json={'error':{'code':190,'message':'access_token=bad-secret expired'}})
    p=Providers(settings,httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PublishError,match='Page Access Token'):
        p.publish({'provider':'facebook'},{'kind':'user'}, {}, None)
    with pytest.raises(PublishError) as e:
        p.publish({'provider':'facebook','external_id':'page'}, {'kind':'page','access_token':'bad-secret'},
                  {'title':'Title','description':'Text'},None)
    assert not e.value.uncertain and 'bad-secret' not in str(e.value)


def test_future_schedule_not_claimed(setup):
    settings,engine,_,client=setup
    headers=login(client);account(engine,settings)
    r=client.post('/api/posts',headers=headers,json=payload(scheduled_at='2030-01-01T00:00:00+07:00'))
    assert r.status_code==200 and claim_post(engine) is None


def test_security_headers_and_no_token_leak(setup):
    settings,engine,_,client=setup
    login(client);account(engine,settings)
    assert client.get('/').headers['X-Frame-Options']=='DENY'
    assert 'frame-ancestors' in client.get('/').headers['Content-Security-Policy']
    assert 'secret' not in client.get('/api/accounts').text


def test_refresh_token_exchange_and_no_leak(setup):
    settings,*_=setup
    settings.google_client_id='client';settings.google_client_secret='client-secret'
    def handler(request):
        assert request.url.host=='oauth2.googleapis.com'
        assert b'grant_type=refresh_token' in request.content
        return httpx.Response(200,json={'access_token':'new-access','expires_in':3600})
    p=Providers(settings,httpx.Client(transport=httpx.MockTransport(handler)))
    result=p.refresh_youtube({'access_token':'old','refresh_token':'durable-refresh','expires_at':0})
    assert result['refresh_token']=='durable-refresh' and result['access_token']=='new-access'
    assert result['expires_at']>time.time()+3500


def test_media_cleanup_keeps_pending_and_unknown(setup,tmp_path):
    settings,engine,_,client=setup
    headers=login(client);account(engine,settings)
    path=tmp_path/'media'/'old.mp4';path.write_bytes(b'example')
    with engine.begin() as c:
        c.execute(media.insert().values(id='old-media',filename='old.mp4',path=str(path),size=7,
            duration=1,width=90,height=160,created_at=time.time()-20*86400))
    result=client.post('/api/posts',headers=headers,json=payload(media_id='old-media'))
    assert result.status_code==200
    maintenance(engine,settings);assert path.exists()
    with engine.begin() as c:
        c.execute(update(posts).values(status='unknown'))
    maintenance(engine,settings);assert path.exists()
    with engine.begin() as c:
        c.execute(update(posts).values(status='submitted'))
    maintenance(engine,settings);assert not path.exists()
