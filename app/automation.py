from __future__ import annotations
"""Private service-to-service API for the Telegram/n8n ingestion workflow.

The browser keeps its own cookie/CSRF authentication. This router uses a separate
bearer credential and a single preselected YouTube destination; it never exposes
the OAuth access or refresh tokens to n8n.
"""
import re
import secrets
import time
from datetime import datetime
from typing import Literal, Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update, or_, and_
from sqlalchemy.exc import IntegrityError

from app.db import accounts, ingests, posts, users, new_id
from app.tiktok_ingest import validate_tiktok_url, DownloadError
from app.quota import validate_and_consume_quota, get_user_quota


class TikTokSubmission(BaseModel):
    request_key: str = Field(min_length=16, max_length=100)
    telegram_chat_id: str = Field(min_length=1, max_length=32)
    telegram_message_id: Optional[str] = Field(default=None, max_length=32)
    source_url: str = Field(min_length=20, max_length=1000)
    title: str = Field(default='', max_length=100)
    description: str = Field(default='', max_length=5000)
    privacy: Literal['private', 'unlisted', 'public'] = 'private'
    shorts_mode: Literal['auto', 'short', 'video'] = 'auto'
    target_platform: Literal['youtube', 'facebook', 'both'] = 'youtube'
    scheduled_at: Optional[datetime] = None
    made_for_kids: bool
    rights_confirmed: Literal[True]


def resolve_automation_user(engine, settings, telegram_chat_id: str) -> str:
    """Resolve or provision user account for this telegram chat id."""
    admin_chat = getattr(settings, 'admin_telegram_chat_id', '5988211094')
    if telegram_chat_id and str(telegram_chat_id) == str(admin_chat):
        with engine.connect() as c:
            owner = c.execute(select(users.c.id).where(users.c.email == 'khuongtran227@gmail.com')).first()
            if owner:
                return owner[0]
        return 'usr_owner_default'

    target_id = f'usr_tg_{telegram_chat_id}'
    with engine.connect() as c:
        existing = c.execute(select(users.c.id).where(users.c.id == target_id)).first()
        if existing:
            return existing[0]

    now = time.time()
    with engine.begin() as c:
        c.execute(users.insert().values(
            id=target_id,
            email=f'tg_{telegram_chat_id}@telegram.toomi.vn',
            password_hash='telegram',
            name=f'Telegram User {telegram_chat_id}',
            tier='free',
            status='active',
            posts_limit=10,
            created_at=now,
            updated_at=now
        ))
    return target_id


def register_automation(app, engine, settings):
    def authorize(request: Request):
        if not settings.tiktok_ingest_enabled:
            raise HTTPException(503, 'Tích hợp Telegram/TikTok chưa được kích hoạt.')
        expected = 'Bearer ' + settings.automation_token
        if not settings.automation_token or not secrets.compare_digest(
            request.headers.get('Authorization', ''), expected
        ):
            raise HTTPException(401, 'Thông tin xác thực dịch vụ không hợp lệ.')

    def resolve_user(telegram_chat_id: str) -> str:
        return resolve_automation_user(engine, settings, telegram_chat_id)

    def view(job_id):
        with engine.connect() as c:
            job = c.execute(select(ingests).where(ingests.c.id == job_id)).mappings().first()
            if not job:
                raise HTTPException(404, 'Không tìm thấy công việc.')
            post = c.execute(select(posts).where(posts.c.id == job['post_id'])).mappings().first() if job['post_id'] else None
        status = post['status'] if post else job['status']
        return {
            'id': job['id'],
            'request_key': job['request_key'],
            'status': status,
            'ingest_status': job['status'],
            'scheduled_at': job['scheduled_at'],
            'post_id': job['post_id'],
            'remote_id': post['remote_id'] if post else None,
            'remote_url': post['remote_url'] if post else None,
            'error': (post['error'] if post else job['error']),
            'terminal': status in ('submitted', 'failed', 'unknown', 'cancelled'),
        }

    @app.get('/internal/v1/quota')
    def get_automation_quota(chat_id: str, request: Request):
        authorize(request)
        user_id = resolve_user(chat_id)
        return get_user_quota(engine, user_id)

    @app.get('/internal/v1/notifications')
    def pending_notifications(request: Request):
        """Poll terminal outcomes; n8n sends Telegram messages and acknowledges them."""
        authorize(request)
        finished = ('submitted', 'failed', 'unknown', 'cancelled')
        with engine.connect() as c:
            rows = c.execute(select(
                ingests.c.id, ingests.c.telegram_chat_id,
                ingests.c.status.label('ingest_status'),
                posts.c.status.label('post_status'),
                posts.c.remote_url, posts.c.error.label('post_error'),
                ingests.c.error.label('ingest_error'),
            ).select_from(ingests.outerjoin(posts, ingests.c.post_id == posts.c.id))
            .where(ingests.c.notified_at.is_(None),
                   or_(and_(ingests.c.post_id.is_(None),
                            ingests.c.status.in_(finished)),
                       posts.c.status.in_(finished)))
            .order_by(ingests.c.created_at).limit(30)).mappings().all()
        return {'notifications': [{
            'id': row['id'],
            'chat_id': row['telegram_chat_id'],
            'status': row['post_status'] or row['ingest_status'],
            'remote_url': row['remote_url'],
            'error': row['post_error'] or row['ingest_error'],
        } for row in rows]}

    @app.post('/internal/v1/tiktok/{job_id}/ack')
    def acknowledge_notification(job_id: str, request: Request):
        authorize(request)
        current = view(job_id)
        if not current['terminal']:
            raise HTTPException(409, 'Chưa có trạng thái cuối để thông báo.')
        with engine.begin() as c:
            result = c.execute(update(ingests).where(
                ingests.c.id == job_id, ingests.c.notified_at.is_(None)
            ).values(notified_at=time.time()))
        return {'ok': True, 'deduplicated': result.rowcount == 0}

    @app.post('/internal/v1/tiktok')
    def submit_tiktok(payload: TikTokSubmission, request: Request):
        authorize(request)
        if not re.fullmatch('[a-zA-Z0-9_-]{16,100}', payload.request_key):
            raise HTTPException(400, 'Khóa yêu cầu không hợp lệ.')
        if not re.fullmatch('-?[0-9]{1,20}', payload.telegram_chat_id):
            raise HTTPException(400, 'Telegram chat ID không hợp lệ.')
        try:
            source_url = validate_tiktok_url(payload.source_url)
        except DownloadError as exc:
            raise HTTPException(400, str(exc)) from exc
        title = payload.title.strip()
        if payload.scheduled_at is not None and payload.scheduled_at.tzinfo is None:
            raise HTTPException(400, 'Thời gian hẹn đăng cần có múi giờ.')

        # 1. Resolve user
        user_id = resolve_user(payload.telegram_chat_id)

        # 2. Look up destination accounts for this user
        with engine.connect() as c:
            user_accounts = c.execute(select(accounts).where(
                accounts.c.user_id == user_id,
                accounts.c.active == True
            )).mappings().all()

        yt_account = next((a for a in user_accounts if a['provider'] == 'youtube'), None)
        if not yt_account and settings.automation_youtube_account_id:
            with engine.connect() as c:
                yt_account = c.execute(select(accounts).where(
                    accounts.c.id == settings.automation_youtube_account_id,
                    accounts.c.provider == 'youtube',
                    accounts.c.active == True,
                )).mappings().first()

        fb_account = next((a for a in user_accounts if a['provider'] == 'facebook'), None)

        if payload.target_platform == 'facebook':
            if not fb_account:
                raise HTTPException(503, 'Chưa kết nối kênh Facebook Page hợp lệ.')
            primary_account = fb_account
        elif payload.target_platform == 'both':
            if not yt_account:
                raise HTTPException(503, 'Chưa kết nối đúng kênh YouTube hợp lệ.')
            if not fb_account:
                raise HTTPException(503, 'Chưa kết nối kênh Facebook Page hợp lệ.')
            primary_account = yt_account
        else: # youtube
            if not yt_account:
                raise HTTPException(503, 'Chưa kết nối đúng kênh YouTube được chỉ định.')
            primary_account = yt_account

        account_id = primary_account['id']

        with engine.connect() as c:
            existing = c.execute(select(ingests.c.id, ingests.c.source_url,
                                        ingests.c.account_id).where(
                ingests.c.request_key == payload.request_key)).mappings().first()
        if existing:
            if existing['source_url'] != source_url or existing['account_id'] != account_id:
                raise HTTPException(409, 'Khóa yêu cầu đã được dùng cho nội dung khác.')
            return {**view(existing['id']), 'ok': True, 'deduplicated': True}

        # 3. Enforce quota: 1 post for single platform, 2 posts for both
        consume_count = 2 if payload.target_platform == 'both' else 1
        quota = validate_and_consume_quota(engine, user_id, count=consume_count)

        job_id = new_id()
        now = time.time()
        scheduled = payload.scheduled_at.timestamp() if payload.scheduled_at else now
        try:
            with engine.begin() as c:
                c.execute(ingests.insert().values(
                    id=job_id,
                    user_id=user_id,
                    request_key=payload.request_key,
                    telegram_chat_id=payload.telegram_chat_id,
                    telegram_message_id=payload.telegram_message_id,
                    source_url=source_url, account_id=account_id,
                    title=title, description=payload.description,
                    privacy=payload.privacy,
                    shorts_mode=payload.shorts_mode,
                    target_platform=payload.target_platform,
                    made_for_kids=payload.made_for_kids,
                    status='pending', scheduled_at=scheduled,
                    created_at=now, updated_at=now))
        except IntegrityError:
            # Concurrent retry: the unique constraint provides database-level dedupe.
            with engine.connect() as c:
                old = c.execute(select(ingests.c.id, ingests.c.source_url,
                                       ingests.c.account_id).where(
                    ingests.c.request_key == payload.request_key)).mappings().first()
            if old and old['source_url'] == source_url and old['account_id'] == account_id:
                return {**view(old['id']), 'ok': True, 'quota': quota, 'deduplicated': True}
            raise HTTPException(409, 'Khóa yêu cầu bị trùng.')

        return {**view(job_id), 'ok': True, 'quota': quota, 'deduplicated': False}

    @app.get('/internal/v1/tiktok/{job_id}')
    def get_tiktok_status(job_id: str, request: Request):
        authorize(request)
        return view(job_id)
