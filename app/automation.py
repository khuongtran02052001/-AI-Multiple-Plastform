"""Private service-to-service API for the Telegram/n8n ingestion workflow.

The browser keeps its own cookie/CSRF authentication. This router uses a separate
bearer credential and a single preselected YouTube destination; it never exposes
the OAuth access or refresh tokens to n8n.
"""
import re
import secrets
import time
from datetime import datetime
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update, or_, and_
from sqlalchemy.exc import IntegrityError

from app.db import accounts, ingests, posts, new_id
from app.tiktok_ingest import validate_tiktok_url, DownloadError


class TikTokSubmission(BaseModel):
    request_key: str = Field(min_length=16, max_length=100)
    telegram_chat_id: str = Field(min_length=1, max_length=32)
    source_url: str = Field(min_length=20, max_length=1000)
    title: str = Field(default='', max_length=100)
    description: str = Field(default='', max_length=5000)
    scheduled_at: datetime | None = None
    made_for_kids: bool
    rights_confirmed: Literal[True]


def register_automation(app, engine, settings):
    def authorize(request: Request):
        if not settings.tiktok_ingest_enabled:
            raise HTTPException(503, 'Tích hợp Telegram/TikTok chưa được kích hoạt.')
        expected = 'Bearer ' + settings.automation_token
        if not settings.automation_token or not secrets.compare_digest(
            request.headers.get('Authorization', ''), expected
        ):
            raise HTTPException(401, 'Thông tin xác thực dịch vụ không hợp lệ.')

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
        if not settings.automation_youtube_account_id:
            raise HTTPException(503, 'Chưa chỉ định kênh YouTube cho automation.')
        with engine.connect() as c:
            account = c.execute(select(accounts.c.id).where(
                accounts.c.id == settings.automation_youtube_account_id,
                accounts.c.provider == 'youtube',
                accounts.c.active == True,
            )).first()
        if not account:
            raise HTTPException(503, 'Chưa kết nối đúng kênh YouTube được chỉ định.')

        with engine.connect() as c:
            existing = c.execute(select(ingests.c.id, ingests.c.source_url,
                                        ingests.c.account_id).where(
                ingests.c.request_key == payload.request_key)).mappings().first()
        if existing:
            if existing['source_url'] != source_url or existing['account_id'] != account.id:
                raise HTTPException(409, 'Khóa yêu cầu đã được dùng cho nội dung khác.')
            return {**view(existing['id']), 'deduplicated': True}

        job_id = new_id()
        now = time.time()
        scheduled = payload.scheduled_at.timestamp() if payload.scheduled_at else now
        try:
            with engine.begin() as c:
                c.execute(ingests.insert().values(
                    id=job_id, request_key=payload.request_key,
                    telegram_chat_id=payload.telegram_chat_id,
                    source_url=source_url, account_id=account.id,
                    title=title, description=payload.description,
                    made_for_kids=payload.made_for_kids,
                    status='pending', scheduled_at=scheduled,
                    created_at=now, updated_at=now))
        except IntegrityError:
            # Concurrent retry: the unique constraint provides database-level dedupe.
            with engine.connect() as c:
                old = c.execute(select(ingests.c.id, ingests.c.source_url,
                                       ingests.c.account_id).where(
                    ingests.c.request_key == payload.request_key)).mappings().first()
            if old and old['source_url'] == source_url and old['account_id'] == account.id:
                return {**view(old['id']), 'deduplicated': True}
            raise HTTPException(409, 'Khóa yêu cầu bị trùng.')

        return {**view(job_id), 'deduplicated': False}

    @app.get('/internal/v1/tiktok/{job_id}')
    def get_tiktok_status(job_id: str, request: Request):
        authorize(request)
        return view(job_id)
