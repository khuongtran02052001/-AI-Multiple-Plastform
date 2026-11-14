from __future__ import annotations
import logging
import threading
import time
import re
from pathlib import Path
from sqlalchemy import select, update, delete
from app.db import accounts, media, posts, sessions, oauth_states, ingests, claim_post, claim_ingest, new_id
from app.providers import PublishError
from app.tiktok_ingest import download_tiktok_video, DownloadError
from app.telegram import update_telegram_progress
import json

logger = logging.getLogger('publisher.worker')


def _get_label(shorts_mode: str, target_platform: str = 'youtube', privacy: str = 'public') -> str:
    if privacy == 'private':
        return '🔒 YouTube Riêng tư'
    if target_platform == 'both':
        return '🚀 YouTube Shorts & FB Reels' if shorts_mode == 'short' else '🚀 YouTube & Facebook'
    if target_platform == 'facebook':
        return '🔵 Facebook Reels' if shorts_mode == 'short' else '🔵 Facebook Video'
    if shorts_mode == 'short':
        return '🔴 YouTube Shorts'
    if shorts_mode == 'video':
        return '🔴 YouTube Video'
    return '🔴 YouTube'


def process_one(engine, providers, vault, settings=None):
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

    bot_token = settings.telegram_bot_token if settings else ''
    chat_id = None
    msg_id = None
    source_url = ''
    label = 'Xuất bản'
    ingest_id = None

    try:
        with engine.connect() as c:
            post = dict(c.execute(select(posts).where(posts.c.id == post_id)).mappings().one())
            account = c.execute(select(accounts).where(accounts.c.id == post['account_id'])).mappings().one()
            file = c.execute(select(media).where(media.c.id == post['media_id'])).mappings().first() if post['media_id'] else None
            ingest_row = c.execute(select(ingests).where(ingests.c.request_key == post['batch_key'])).mappings().first()

        if ingest_row:
            ingest_id = ingest_row.get('id')
            chat_id = ingest_row.get('telegram_chat_id')
            msg_id = ingest_row.get('telegram_message_id')
            source_url = ingest_row.get('source_url', '')
            target_platform = ingest_row.get('target_platform') or 'youtube'
            label = _get_label(ingest_row.get('shorts_mode') or 'auto', target_platform, ingest_row.get('privacy') or 'public')
        else:
            target_platform = 'youtube'

        if not account['active']:
            raise PublishError('Tài khoản đã ngắt kết nối.')
        if file and not Path(file['path']).is_file():
            raise PublishError('Video không còn trên VPS. Tải lại video để tạo bài mới.')

        tokens = vault.decrypt(account['tokens'])
        if account['provider'] == 'youtube':
            tokens = providers.refresh_youtube(tokens)
            with engine.begin() as c:
                c.execute(update(accounts).where(accounts.c.id == account['id']).values(tokens=vault.encrypt(tokens)))

        update_telegram_progress(bot_token, chat_id, msg_id, source_url, label, 85, step_index=4, target_platform=target_platform)

        remote_id, url = providers.publish(account, tokens, post, file)
        if post.get('shorts') and account['provider'] == 'youtube':
            url = f'https://www.youtube.com/shorts/{remote_id}'
        now = time.time()
        with engine.begin() as c:
            c.execute(update(posts).where(posts.c.id == post_id).values(status='submitted',
                remote_id=remote_id, remote_url=url, error=None, lease_until=None, updated_at=now))

            # Multi-channel batch check
            batch_posts = c.execute(select(posts).where(posts.c.batch_key == post['batch_key'])).mappings().all()
            pending_batch = [p for p in batch_posts if p['status'] in ('queued', 'posting')]
            submitted_batch = [p for p in batch_posts if p['status'] == 'submitted']

            if not pending_batch:
                yt_link = next((p['remote_url'] for p in submitted_batch if 'youtube.com' in (p['remote_url'] or '')), '')
                fb_link = next((p['remote_url'] for p in submitted_batch if 'facebook.com' in (p['remote_url'] or '')), '')
                notified = update_telegram_progress(
                    bot_token, chat_id, msg_id, source_url, label, 100, step_index=4,
                    video_title=post['title'], youtube_url=yt_link, facebook_url=fb_link,
                    target_platform=target_platform
                )
                if ingest_id and notified:
                    c.execute(update(ingests).where(ingests.c.id == ingest_id).values(notified_at=now))
            else:
                update_telegram_progress(
                    bot_token, chat_id, msg_id, source_url, label, 85, step_index=4,
                    target_platform=target_platform, file_info=f"Đã đăng lên {account['provider']}, đang tiếp tục..."
                )

    except PublishError as exc:
        now = time.time()
        notified = update_telegram_progress(bot_token, chat_id, msg_id, source_url, label, -1, step_index=4,
                                 target_platform=target_platform, error_message=str(exc))
        with engine.begin() as c:
            c.execute(update(posts).where(posts.c.id == post_id).values(
                status='unknown' if exc.uncertain else 'failed', error=str(exc),
                lease_until=None, updated_at=now))
            if ingest_id and notified:
                c.execute(update(ingests).where(ingests.c.id == ingest_id).values(notified_at=now))
    except Exception as exc:
        now = time.time()
        logger.error('Job interrupted; marked unknown. Check the platform before retrying.')
        notified = update_telegram_progress(bot_token, chat_id, msg_id, source_url, label, -1, step_index=4,
                                 target_platform=target_platform, error_message="Lỗi gián đoạn khi xuất bản. Kiểm tra kênh trước khi thử lại.")
        with engine.begin() as c:
            c.execute(update(posts).where(posts.c.id == post_id).values(status='unknown',
                error='Không xác định được kết quả. Kiểm tra trực tiếp trên nền tảng.',
                lease_until=None, updated_at=now))
            if ingest_id and notified:
                c.execute(update(ingests).where(ingests.c.id == ingest_id).values(notified_at=now))
    finally:
        heartbeat_stop.set()
        thread.join(timeout=2)
    return True


def process_one_ingest(engine, settings, downloader=download_tiktok_video):
    """Download user-authorized media and create exactly one publish-queue job."""
    if not settings.tiktok_ingest_enabled:
        return False
    ingest_id = claim_ingest(engine)
    if not ingest_id:
        return False
    file = None
    chat_id = None
    msg_id = None
    source_url = ''
    label = 'Xuất bản'

    try:
        with engine.connect() as c:
            job = dict(c.execute(select(ingests).where(ingests.c.id == ingest_id)).mappings().one())
            account = c.execute(select(accounts).where(accounts.c.id == job['account_id'])).mappings().one()

        chat_id = job.get('telegram_chat_id')
        msg_id = job.get('telegram_message_id')
        source_url = job.get('source_url', '')
        privacy = job.get('privacy') or 'private'
        shorts_mode = job.get('shorts_mode') or 'auto'
        target_platform = job.get('target_platform') or 'youtube'
        label = _get_label(shorts_mode, target_platform, privacy)

        if not account['active'] or account['provider'] not in ('youtube', 'facebook'):
            raise DownloadError('Kênh đã ngắt kết nối hoặc không hợp lệ.')

        update_telegram_progress(settings.telegram_bot_token, chat_id, msg_id, source_url, label, 35, step_index=2, target_platform=target_platform)

        file = downloader(settings, job['source_url'])
        source = file.pop('source_metadata', {})
        title = job['title'].strip() or source.get('title') or 'Video TikTok'
        description = job['description'].strip() or source.get('description', '')

        is_vertical = file['width'] <= file['height']
        is_short_duration = file['duration'] <= 180
        file_info_note = f"{file['width']}x{file['height']}"

        if shorts_mode == 'short':
            shorts = True
            if not is_vertical:
                update_telegram_progress(
                    settings.telegram_bot_token, chat_id, msg_id, source_url, label, 50, step_index=3,
                    file_info="Chuyển sang 9:16 Shorts/Reels...", target_platform=target_platform
                )
                from app.tiktok_ingest import convert_to_vertical_short
                file = convert_to_vertical_short(file)
                is_vertical = True
                file_info_note = "Đã chuyển dọc 720x1280"
            else:
                file_info_note = f"Gốc dọc {file['width']}x{file['height']}" 
            if '#Shorts' not in title and '#shorts' not in title and '#Shorts' not in description and '#shorts' not in description:
                if len(title) <= 92:
                    title = f"{title} #Shorts"
                else:
                    description = (description + '\n\n#Shorts').strip()
        elif shorts_mode == 'video':
            shorts = False
            title = re.sub(r'#shorts? ', '', title, flags=re.IGNORECASE).strip()
        else:
            shorts = is_short_duration and is_vertical

        now = time.time()
        file['user_id'] = job.get('user_id')
        with engine.begin() as c:
            c.execute(media.insert().values(**file))

            if target_platform == 'both':
                user_accounts = c.execute(select(accounts).where(
                    accounts.c.user_id == job.get('user_id'),
                    accounts.c.active == True
                )).mappings().all()
                yt_acc = next((a for a in user_accounts if a['provider'] == 'youtube'), None)
                if not yt_acc and settings.automation_youtube_account_id:
                    yt_acc = c.execute(select(accounts).where(
                        accounts.c.id == settings.automation_youtube_account_id,
                        accounts.c.provider == 'youtube',
                        accounts.c.active == True
                    )).mappings().first()
                fb_acc = next((a for a in user_accounts if a['provider'] == 'facebook'), None)

                post_ids = []
                if yt_acc:
                    pid_yt = new_id()
                    post_ids.append(pid_yt)
                    c.execute(posts.insert().values(
                        id=pid_yt, user_id=job.get('user_id'), batch_key=job['request_key'], account_id=yt_acc['id'],
                        media_id=file['id'], title=title, description=description,
                        tags=json.dumps(source.get('tags', []), ensure_ascii=False), privacy=privacy, made_for_kids=job['made_for_kids'],
                        shorts=shorts,
                        status='queued', scheduled_at=job['scheduled_at'], created_at=now,
                        updated_at=now))
                if fb_acc:
                    pid_fb = new_id()
                    post_ids.append(pid_fb)
                    c.execute(posts.insert().values(
                        id=pid_fb, user_id=job.get('user_id'), batch_key=job['request_key'], account_id=fb_acc['id'],
                        media_id=file['id'], title=title, description=description,
                        tags=json.dumps(source.get('tags', []), ensure_ascii=False), privacy='public', made_for_kids=False,
                        shorts=shorts,
                        status='queued', scheduled_at=job['scheduled_at'], created_at=now,
                        updated_at=now))

                primary_pid = post_ids[0] if post_ids else None
                c.execute(update(ingests).where(ingests.c.id == ingest_id).values(
                    status='queued', post_id=primary_pid, error=None, lease_until=None, updated_at=now))
            else:
                post_id = new_id()
                c.execute(posts.insert().values(
                    id=post_id, user_id=job.get('user_id'), batch_key=job['request_key'], account_id=job['account_id'],
                    media_id=file['id'], title=title, description=description,
                    tags=json.dumps(source.get('tags', []), ensure_ascii=False), privacy=privacy, made_for_kids=job['made_for_kids'],
                    shorts=shorts,
                    status='queued', scheduled_at=job['scheduled_at'], created_at=now,
                    updated_at=now))
                c.execute(update(ingests).where(ingests.c.id == ingest_id).values(
                    status='queued', post_id=post_id, error=None, lease_until=None, updated_at=now))

        update_telegram_progress(settings.telegram_bot_token, chat_id, msg_id, source_url, label, 65, step_index=3,
                                 file_info=file_info_note, target_platform=target_platform)

    except Exception as exc:
        now = time.time()
        if file:
            try:
                Path(file['path']).unlink(missing_ok=True)
            except OSError:
                pass
        logger.error('Video import failed for ingestion job.')
        notified = update_telegram_progress(settings.telegram_bot_token, chat_id, msg_id, source_url, label, -1, step_index=2,
                                 target_platform=target_platform, error_message='Không lấy được video hợp lệ. Kiểm tra quyền tải và liên kết.')
        with engine.begin() as c:
            c.execute(update(ingests).where(ingests.c.id == ingest_id).values(
                status='failed', error='Không lấy được video hợp lệ. Kiểm tra quyền tải và liên kết.',
                lease_until=None, updated_at=now, notified_at=now if notified else None))
    return True


def maintenance(engine, settings):
    now = time.time()
    with engine.begin() as c:
        c.execute(update(posts).where(posts.c.status == 'posting', posts.c.lease_until < now)
            .values(status='unknown', error='Tiến trình dừng khi đang đăng. Kiểm tra nền tảng trước khi đăng lại.',
                    lease_until=None, updated_at=now))
        c.execute(delete(sessions).where(sessions.c.expires_at < now))
        c.execute(delete(oauth_states).where(oauth_states.c.expires_at < now))
        c.execute(update(ingests).where(ingests.c.status == 'downloading',
            ingests.c.lease_until < now).values(
            status='failed', lease_until=None, updated_at=now, notified_at=now,
            error='Tải video bị gián đoạn. Cần gửi một yêu cầu mới sau khi kiểm tra.'))
        used = select(posts.c.media_id).where(posts.c.status.in_(['draft', 'queued', 'posting', 'unknown']),
                                             posts.c.media_id.is_not(None))
        expired = c.execute(select(media).where(media.c.created_at < now - settings.retention_days * 86400,
            ~media.c.id.in_(used))).mappings().all()
        for item in expired:
            Path(item['path']).unlink(missing_ok=True)
            c.execute(update(posts).where(posts.c.media_id == item['id']).values(media_id=None))
            c.execute(delete(media).where(media.c.id == item['id']))
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
            if process_one_ingest(engine, settings):
                continue
            if not process_one(engine, providers, vault, settings):
                stop.wait(3)
        except Exception:
            logger.error('Worker cannot reach database. Waiting before next check.')
            stop.wait(10)
