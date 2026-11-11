import logging
import threading
import time
from pathlib import Path
from sqlalchemy import select, update, delete
from app.db import accounts, media, posts, sessions, oauth_states, claim_post
from app.providers import PublishError

logger = logging.getLogger('publisher.worker')


def process_one(engine, providers, vault):
    post_id = claim_post(engine)
    if not post_id:
        return False
    heartbeat_stop = threading.Event()

    def heartbeat():
        while not heartbeat_stop.wait(30):
            try:
                with engine.begin() as c:
                    c.execute(update(posts).where(posts.c.id == post_id, posts.c.status == 'posting')
                        .values(lease_until=time.time() + 180))
            except Exception:
                logger.error('Could not renew job lease; check database connectivity.')

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        with engine.connect() as c:
            post = dict(c.execute(select(posts).where(posts.c.id == post_id)).mappings().one())
            account = c.execute(select(accounts).where(accounts.c.id == post['account_id'])).mappings().one()
            file = c.execute(select(media).where(media.c.id == post['media_id'])).mappings().first() if post['media_id'] else None
        if not account['active']:
            raise PublishError('Tài khoản đã ngắt kết nối.')
        if file and not Path(file['path']).is_file():
            raise PublishError('Video không còn trên VPS. Tải lại video để tạo bài mới.')
        tokens = vault.decrypt(account['tokens'])
        if account['provider'] == 'youtube':
            tokens = providers.refresh_youtube(tokens)
            with engine.begin() as c:
                c.execute(update(accounts).where(accounts.c.id == account['id']).values(tokens=vault.encrypt(tokens)))
        remote_id, url = providers.publish(account, tokens, post, file)
        with engine.begin() as c:
            c.execute(update(posts).where(posts.c.id == post_id).values(status='submitted',
                remote_id=remote_id, remote_url=url, error=None, lease_until=None, updated_at=time.time()))
    except PublishError as exc:
        with engine.begin() as c:
            c.execute(update(posts).where(posts.c.id == post_id).values(
                status='unknown' if exc.uncertain else 'failed', error=str(exc),
                lease_until=None, updated_at=time.time()))
    except Exception:
        # Unknown exceptions may happen after a successful external write.
        # Never retry automatically, never log exception text that can contain credentials.
        logger.error('Job interrupted; marked unknown. Check the platform before retrying.')
        with engine.begin() as c:
            c.execute(update(posts).where(posts.c.id == post_id).values(status='unknown',
                error='Không xác định được kết quả. Kiểm tra trực tiếp trên nền tảng.',
                lease_until=None, updated_at=time.time()))
    finally:
        heartbeat_stop.set()
        thread.join(timeout=2)
    return True


def maintenance(engine, settings):
    now = time.time()
    with engine.begin() as c:
        c.execute(update(posts).where(posts.c.status == 'posting', posts.c.lease_until < now)
            .values(status='unknown', error='Tiến trình dừng khi đang đăng. Kiểm tra nền tảng trước khi đăng lại.',
                    lease_until=None, updated_at=now))
        c.execute(delete(sessions).where(sessions.c.expires_at < now))
        c.execute(delete(oauth_states).where(oauth_states.c.expires_at < now))
        # Keep media used by unresolved, pending or draft posts.
        used = select(posts.c.media_id).where(posts.c.status.in_(['draft', 'queued', 'posting', 'unknown']),
                                             posts.c.media_id.is_not(None))
        expired = c.execute(select(media).where(media.c.created_at < now - settings.retention_days * 86400,
            ~media.c.id.in_(used))).mappings().all()
        for item in expired:
            Path(item['path']).unlink(missing_ok=True)
            c.execute(update(posts).where(posts.c.media_id == item['id']).values(media_id=None))
            c.execute(delete(media).where(media.c.id == item['id']))
    # Remove old partial files left by a process crash, never current uploads.
    for path in (settings.data_dir / 'media').glob('*.part'):
        if path.stat().st_mtime < now - 86400:
            path.unlink(missing_ok=True)


def loop(engine, providers, vault, settings, stop):
    last_cleanup = 0
    while not stop.is_set():
        try:
            if time.time() - last_cleanup > 60:
                maintenance(engine, settings)
                last_cleanup = time.time()
            if not process_one(engine, providers, vault):
                stop.wait(3)
        except Exception:
            logger.error('Worker cannot reach database. Waiting before next check.')
            stop.wait(10)
