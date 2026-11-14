from __future__ import annotations
import base64
import hashlib
from urllib.parse import urlencode
import httpx
import json

import secrets

import subprocess

import threading

import time

from collections import defaultdict, deque

from contextlib import asynccontextmanager

from datetime import datetime, timezone

from pathlib import Path

from typing import Literal



from fastapi import FastAPI, Request, HTTPException, UploadFile, File

from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, PlainTextResponse, HTMLResponse

from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field

from sqlalchemy import select, update, delete, func, or_, and_

from sqlalchemy.exc import IntegrityError

from app.config import settings as default_settings

from app.db import make_engine, initialize, accounts, media, posts, sessions, oauth_states, ingests, users, usage_quotas, new_id

from app.security import Vault, verify_password, password_hash, digest

from app.providers import Providers, PublishError

from app.worker import loop

from app.automation import register_automation

from app.quota import get_user_quota, validate_and_consume_quota

from app.auth import (generate_api_key, resolve_api_key, list_user_api_keys,

                      revoke_user_api_key, extract_api_key_from_request)





class Login(BaseModel):

    password: str = Field(min_length=1, max_length=512)

    email: str | None = None






class GoogleCredentialPayload(BaseModel):
    credential: str = Field(min_length=10, max_length=4096)

class RegisterPayload(BaseModel):

    email: str = Field(min_length=3, max_length=120)

    password: str = Field(min_length=6, max_length=128)

    name: str = Field(default='Customer', min_length=1, max_length=100)





class CreatePost(BaseModel):

    batch_key: str = Field(min_length=16, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')

    account_ids: list[str] = Field(min_length=1, max_length=10)

    title: str = Field(min_length=1, max_length=100)

    description: str = Field(default='', max_length=5000)

    tags: list[str] = Field(default_factory=list, max_length=30)

    media_id: str | None = None

    privacy: Literal['private', 'unlisted', 'public'] = 'private'

    made_for_kids: bool = False

    shorts: bool = True

    action: Literal['draft', 'queue'] = 'draft'

    scheduled_at: datetime | None = None





class CreateApiKeyPayload(BaseModel):

    name: str = Field(default='n8n Integration', min_length=1, max_length=100)






class AdminUserTierUpdate(BaseModel):
    tier: str
    posts_limit: int

class AdminUserStatusUpdate(BaseModel):
    status: str

class ExternalPublishPayload(BaseModel):

    source_url: str = Field(min_length=15, max_length=1000)

    account_id: str | None = None

    title: str = Field(default='', max_length=100)

    description: str = Field(default='', max_length=5000)

    privacy: Literal['private', 'unlisted', 'public'] = 'private'

    shorts_mode: Literal['auto', 'short', 'video'] = 'auto'

    made_for_kids: bool = False

    telegram_chat_id: str | None = None

    telegram_message_id: str | None = None

    request_key: str | None = None





def create_app(config=None, engine=None, providers=None):

    s = config or default_settings

    s.validate()

    db = engine or make_engine(s.database_url)

    vault = Vault(s.encryption_key)

    api = providers or Providers(s)

    stop = threading.Event()

    upload_lock = threading.Lock()

    attempts = defaultdict(deque)

    attempts_lock = threading.Lock()



    @asynccontextmanager

    async def lifespan(app):

        initialize(db, s.admin_password_hash)

        worker = None

        if s.worker_enabled:

            worker = threading.Thread(target=loop, args=(db, api, vault, s, stop), daemon=True)

            worker.start()

        yield

        stop.set()

        if worker:

            worker.join(timeout=5)

        # Daemon uploads may finish on normal shutdown; an interrupted job becomes unknown.

        if not worker or not worker.is_alive():

            api.close()

            db.dispose()



    app = FastAPI(title='OmniPublish', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    app.state.db = db

    app.state.vault = vault

    register_automation(app, db, s)




    def is_admin_session(session: dict) -> bool:
        with db.connect() as c:
            u = c.execute(select(users).where(users.c.id == session.get('user_id'))).mappings().first()
        return bool(u and u['status'] == 'active' and u['role'] in ('admin', 'superadmin'))

    def require_owner(session, row):
        if not row:
            raise HTTPException(404, 'Không tìm thấy dữ liệu.')
        if row.get('user_id') != session.get('user_id') and not is_admin_session(session):
            raise HTTPException(403, 'Bạn không có quyền truy cập dữ liệu này.')

    def require_admin(request: Request):
        session = require_session(request)
        if not is_admin_session(session):
            raise HTTPException(403, 'Yêu cầu quyền Super Admin.')
        return session

    def admin_mutation_auth(request: Request):
        session = require_admin(request)
        if request.headers.get('origin') and request.headers.get('origin') != s.base_url:
            raise HTTPException(403, 'Origin không hợp lệ.')
        if not secrets.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):
            raise HTTPException(403, 'CSRF token không hợp lệ.')
        return session

    def require_session(request: Request):

        raw = request.cookies.get('sp_session', '')

        if not raw:

            raise HTTPException(401, 'Đăng nhập để tiếp tục.')

        with db.connect() as c:

            row = c.execute(select(sessions).where(sessions.c.id == digest(raw),

                sessions.c.expires_at > time.time())).mappings().first()

        if not row:

            raise HTTPException(401, 'Phiên đăng nhập đã hết hạn.')

        d = dict(row)

        if not d.get('user_id'):
            raise HTTPException(401, 'Phiên cũ không hợp lệ. Đăng nhập lại.')
        with db.connect() as c:
            current_user = c.execute(select(users).where(users.c.id == d['user_id'])).mappings().first()
        if not current_user or current_user['status'] != 'active':
            raise HTTPException(401, 'Tài khoản không còn hoạt động.')

        return d



    def mutation_auth(request: Request):

        session = require_session(request)

        if request.headers.get('origin') != s.base_url:

            raise HTTPException(403, 'Origin không hợp lệ.')

        if not secrets.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):

            raise HTTPException(403, 'CSRF token không hợp lệ.')

        return session



    @app.middleware('http')

    async def headers(request, call_next):

        if request.method in ('POST', 'PUT', 'PATCH') and request.url.path not in ('/api/media', '/api/v1/publish'):

            length = request.headers.get('content-length', '0')

            if not length.isdigit() or int(length) > 65536:

                return JSONResponse({'detail': 'Yêu cầu quá lớn.'}, status_code=413)

        # Reject unauthenticated uploads before multipart parsing can spool to disk.

        if request.url.path == '/api/media' and request.method == 'POST':

            try:

                mutation_auth(request)

                length = request.headers.get('content-length')

                if not length or not length.isdigit():

                    return JSONResponse({'detail': 'Yêu cầu Content-Length khi tải video.'}, status_code=411)

                if int(length) > (s.max_upload_mb + 2) * 1024**2:

                    return JSONResponse({'detail': 'Video vượt giới hạn dung lượng.'}, status_code=413)

            except HTTPException as exc:

                return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)

        response = await call_next(request)

        response.headers.update({

            'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',

            'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store',

            'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://accounts.google.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' blob: https:; media-src 'self' blob:; connect-src 'self' https:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",

            'Permissions-Policy': 'camera=(), microphone=(), geolocation=()'})

        if s.secure:

            response.headers['Strict-Transport-Security'] = 'max-age=31536000'

        return response



    @app.exception_handler(PublishError)

    async def provider_error(request, exc):

        return JSONResponse({'detail': str(exc)}, status_code=400)



    @app.get('/healthz')

    def health():

        try:

            with db.connect() as c:

                c.execute(select(func.count()).select_from(accounts))

            return {'ok': True}

        except Exception:

            return JSONResponse({'ok': False}, status_code=503)



    @app.post('/api/login')

    def login(payload: Login, request: Request):

        if request.headers.get('origin') != s.base_url:

            raise HTTPException(403, 'Origin không hợp lệ.')

        ip = request.client.host if request.client else 'unknown'

        with attempts_lock:

            now = time.time()

            for key in list(attempts):

                while attempts[key] and attempts[key][0] < now - 900:

                    attempts[key].popleft()

                if not attempts[key]:

                    del attempts[key]

            if len(attempts[ip]) >= 10:

                raise HTTPException(429, 'Quá nhiều lần đăng nhập. Thử lại sau 15 phút.')

            attempts[ip].append(now)



        user_id = None

        if payload.email and payload.email.strip():

            email_clean = payload.email.strip().lower()

            with db.connect() as c:

                u = c.execute(select(users).where(users.c.email == email_clean)).mappings().first()

            if not u or not verify_password(payload.password, u['password_hash']):

                raise HTTPException(401, 'Email hoặc mật khẩu không chính xác.')

            if u['status'] != 'active':

                raise HTTPException(403, 'Tài khoản người dùng đã bị tạm khóa.')

            user_id = u['id']

        else:

            if not verify_password(payload.password, s.admin_password_hash):

                raise HTTPException(401, 'Mật khẩu workspace không đúng.')

            user_id = 'usr_owner_default'



        raw = secrets.token_urlsafe(32)

        csrf = secrets.token_urlsafe(32)

        with db.begin() as c:

            c.execute(sessions.insert().values(

                id=digest(raw),

                user_id=user_id,

                csrf=csrf,

                expires_at=time.time() + 28800

            ))

        response = JSONResponse({'csrf': csrf, 'user_id': user_id})

        response.set_cookie('sp_session', raw, httponly=True, secure=s.secure,

                            samesite='lax', max_age=28800, path='/')

        return response



    @app.post('/api/register')

    def register_customer(payload: RegisterPayload, request: Request):

        if request.headers.get('origin') != s.base_url:

            raise HTTPException(403, 'Origin không hợp lệ.')

        email_clean = payload.email.strip().lower()

        if '@' not in email_clean or '.' not in email_clean:

            raise HTTPException(400, 'Địa chỉ email không hợp lệ.')



        with db.connect() as c:

            existing = c.execute(select(users.c.id).where(users.c.email == email_clean)).first()

        if existing:

            raise HTTPException(409, 'Email này đã tồn tại. Vui lòng chuyển sang tab Đăng nhập.')



        user_id = 'usr_' + new_id()[:12]

        now = time.time()

        pwd_hash = password_hash(payload.password)



        with db.begin() as c:

            c.execute(users.insert().values(

                id=user_id,

                email=email_clean,

                password_hash=pwd_hash,

                name=payload.name.strip() or 'Khách hàng',

                tier='free',

                status='active',

                posts_limit=10,

                created_at=now,

                updated_at=now

            ))



        # Auto create a default API key for customer

        raw_key, key_info = generate_api_key(db, user_id, 'Khóa n8n Mặc định')



        raw = secrets.token_urlsafe(32)

        csrf = secrets.token_urlsafe(32)

        with db.begin() as c:

            c.execute(sessions.insert().values(

                id=digest(raw),

                user_id=user_id,

                csrf=csrf,

                expires_at=now + 28800

            ))

        response = JSONResponse({

            'csrf': csrf,

            'user_id': user_id,

            'default_api_key': raw_key,

            'message': 'Đăng ký tài khoản thành công! Bạn nhận được 10 bài đăng miễn phí mỗi tháng.'

        })

        response.set_cookie('sp_session', raw, httponly=True, secure=s.secure,

                            samesite='lax', max_age=28800, path='/')

        return response


    def _process_google_user(email: str, name: str) -> tuple[str, str, str, str | None, bool]:
        email_clean = email.strip().lower()
        now = time.time()
        with db.connect() as c:
            existing = c.execute(select(users).where(users.c.email == email_clean)).mappings().first()

        if existing:
            if existing['status'] != 'active':
                raise HTTPException(403, 'Tài khoản người dùng đã bị tạm khóa.')
            user_id = existing['id']
            created_new = False
            default_api_key = None
        else:
            user_id = 'usr_' + new_id()[:12]
            with db.begin() as c:
                c.execute(users.insert().values(
                    id=user_id,
                    email=email_clean,
                    password_hash=password_hash(secrets.token_urlsafe(32)),
                    name=name.strip() or 'Khách hàng Google',
                    tier='free',
                    status='active',
                    posts_limit=10,
                    created_at=now,
                    updated_at=now
                ))
            raw_key, _ = generate_api_key(db, user_id, 'Khóa n8n Mặc định')
            default_api_key = raw_key
            created_new = True

        raw = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        with db.begin() as c:
            c.execute(sessions.insert().values(
                id=digest(raw),
                user_id=user_id,
                csrf=csrf,
                expires_at=now + 28800
            ))
        return raw, csrf, user_id, default_api_key, created_new

    @app.get('/api/auth/config')
    def auth_config():
        return {
            'google_enabled': bool(s.google_client_id and s.google_client_secret),
            'google_client_id': s.google_client_id
        }

    @app.post('/api/auth/google/credential')
    def google_credential_login(payload: GoogleCredentialPayload, request: Request):
        if request.headers.get('origin') != s.base_url:
            raise HTTPException(403, 'Origin không hợp lệ.')
        if not s.google_client_id:
            raise HTTPException(400, 'Chưa cấu hình Google OAuth Client ID.')
        try:
            r = httpx.get('https://oauth2.googleapis.com/tokeninfo',
                          params={'id_token': payload.credential}, timeout=10)
        except Exception:
            raise HTTPException(502, 'Không thể kết nối đến máy chủ Google.')
        if r.status_code != 200:
            raise HTTPException(400, 'Mã xác thực Google không hợp lệ hoặc đã hết hạn.')
        info = r.json()
        if info.get('aud') != s.google_client_id:
            raise HTTPException(400, 'Google Client ID không khớp.')
        if str(info.get('email_verified', '')).lower() != 'true':
            raise HTTPException(400, 'Email Google chưa được xác thực.')
        raw, csrf, user_id, default_api_key, created_new = _process_google_user(
            info.get('email', ''), info.get('name', '')
        )
        response = JSONResponse({
            'ok': True,
            'csrf': csrf,
            'user_id': user_id,
            'default_api_key': default_api_key,
            'created_new': created_new,
            'message': 'Đăng ký thành công! Bạn nhận được 10 bài đăng miễn phí mỗi tháng.' if created_new else 'Đăng nhập Google thành công!'
        })
        response.set_cookie('sp_session', raw, httponly=True, secure=s.secure,
                            samesite='lax', max_age=28800, path='/')
        return response

    @app.get('/api/auth/google/start')
    def google_oauth_start():
        if not s.google_client_id or not s.google_client_secret:
            raise HTTPException(400, 'Chưa cấu hình Google OAuth trong .env trên VPS.')
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        with db.begin() as c:
            c.execute(oauth_states.insert().values(
                id=digest(state),
                session_id='google_auth_flow',
                provider='google_auth',
                verifier=vault.encrypt(verifier),
                expires_at=time.time() + 600
            ))
        redirect_uri = f"{s.base_url}/api/auth/google/callback"
        params = {
            'client_id': s.google_client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'openid email profile',
            'access_type': 'online',
            'prompt': 'select_account',
            'state': state,
            'code_challenge': challenge,
            'code_challenge_method': 'S256'
        }
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)
        return RedirectResponse(url, status_code=303)

    @app.get('/api/auth/google/callback')
    @app.get('/oauth/google/callback')
    def google_oauth_callback(request: Request, state: str = '', code: str = '', error: str = ''):
        if error or not code:
            return RedirectResponse(f'/?auth_error={error or "cancelled"}', status_code=303)
        with db.begin() as c:
            row = c.execute(
                select(oauth_states).where(
                    oauth_states.c.id == digest(state),
                    oauth_states.c.provider == 'google_auth',
                    oauth_states.c.expires_at > time.time()
                )
            ).mappings().first()
            if not row:
                return RedirectResponse('/?auth_error=expired_session', status_code=303)
            c.execute(delete(oauth_states).where(oauth_states.c.id == row['id']))

        verifier = vault.decrypt(row['verifier'])
        redirect_uri = f"{s.base_url}/oauth/google/callback" if request.url.path.endswith('/oauth/google/callback') else f"{s.base_url}/api/auth/google/callback"

        try:
            token_resp = httpx.post('https://oauth2.googleapis.com/token', data={
                'client_id': s.google_client_id,
                'client_secret': s.google_client_secret,
                'code': code,
                'code_verifier': verifier,
                'grant_type': 'authorization_code',
                'redirect_uri': redirect_uri
            }, timeout=15)
            if token_resp.status_code != 200:
                return RedirectResponse('/?auth_error=token_exchange_failed', status_code=303)
            tokens = token_resp.json()
            userinfo_resp = httpx.get('https://www.googleapis.com/oauth2/v3/userinfo', headers={
                'Authorization': f"Bearer {tokens['access_token']}"
            }, timeout=15)
            if userinfo_resp.status_code != 200:
                return RedirectResponse('/?auth_error=userinfo_failed', status_code=303)
            userinfo = userinfo_resp.json()
        except Exception:
            return RedirectResponse('/?auth_error=google_network_error', status_code=303)

        raw, csrf, user_id, default_api_key, created_new = _process_google_user(
            userinfo.get('email', ''), userinfo.get('name', '')
        )
        redirect_url = '/?auth=registered' if created_new else '/?auth=success'
        response = RedirectResponse(redirect_url, status_code=303)
        response.set_cookie('sp_session', raw, httponly=True, secure=s.secure,
                            samesite='lax', max_age=28800, path='/')
        return response



    @app.get('/api/session')

    def session_info(request: Request):

        session = require_session(request)

        user_id = session.get('user_id') or 'usr_owner_default'

        with db.connect() as c:

            u = c.execute(select(users).where(users.c.id == user_id)).mappings().first()

        is_admin = is_admin_session(session)
        user_info = {
            'id': user_id,
            'email': u['email'] if u else 'admin@toomi.vn',
            'name': u['name'] if u else 'Workspace Admin',
            'tier': u['tier'] if u else ('pro' if is_admin else 'free'),
            'role': u['role'] if u else 'user',
            'posts_limit': u['posts_limit'] if u else 999999
        }

        return {'csrf': session['csrf'], 'user': user_info}



    @app.post('/api/logout')

    def logout(request: Request):

        session = mutation_auth(request)

        with db.begin() as c:

            c.execute(delete(sessions).where(sessions.c.id == session['id']))

            c.execute(delete(oauth_states).where(oauth_states.c.session_id == session['id']))

        response = JSONResponse({'ok': True})

        response.delete_cookie('sp_session')

        return response



    @app.post('/api/webhooks/payment')

    def webhook_payment(payload: dict, request: Request):

        """VietQR / SePay payment webhook to automatically upgrade customer to Pro."""

        content = str(payload.get('content') or payload.get('description') or payload.get('order_info') or '').upper().strip()

        amount = float(payload.get('transferAmount') or payload.get('amount') or payload.get('money') or 0)



        import re

        match = re.search(r'OP\s+([A-Z0-9_.@-]+)', content)

        if not match:

            return {'ok': False, 'message': 'Không tìm thấy cú pháp OP trong nội dung chuyển khoản.'}



        target = match.group(1).lower()

        with db.connect() as c:
            u = c.execute(select(users).where(
                or_(
                    users.c.id == target,
                    users.c.id == f'usr_{target}',
                    users.c.email == target,
                    users.c.email.ilike(f'{target}@%'),
                    users.c.id.ilike(f'%{target}%')
                )
            )).mappings().first()



        if not u:

            return {'ok': False, 'message': f'Không tìm thấy người dùng phù hợp với {target}.'}



        now = time.time()

        with db.begin() as c:

            c.execute(update(users).where(users.c.id == u['id']).values(

                tier='pro',

                posts_limit=999999,

                updated_at=now

            ))



        return {

            'ok': True,

            'upgraded_user': u['id'],

            'email': u['email'],

            'new_tier': 'pro',

            'message': f"Đã nâng cấp tài khoản {u['email']} lên gói Pro không giới hạn!"

        }



    # --- USER QUOTA & API KEYS (SAAS CORE) ---



    @app.get('/api/user/quota')

    def user_quota(request: Request):

        session = require_session(request)

        return get_user_quota(db, session['user_id'])



    @app.get('/api/user/api-keys')

    def user_keys(request: Request):

        session = require_session(request)

        return list_user_api_keys(db, session['user_id'])



    @app.post('/api/user/api-keys')

    def create_key(payload: CreateApiKeyPayload, request: Request):

        session = mutation_auth(request)

        raw_key, info = generate_api_key(db, session['user_id'], payload.name)

        return {'raw_key': raw_key, 'key_info': info}



    @app.delete('/api/user/api-keys/{key_id}')

    def revoke_key(key_id: str, request: Request):

        session = mutation_auth(request)

        revoked = revoke_user_api_key(db, session['user_id'], key_id)

        if not revoked:

            raise HTTPException(404, 'Không tìm thấy API Key.')

        return {'ok': True}



    # --- EXTERNAL API FOR n8n & AUTOMATION ---



    @app.get('/api/v1/quota')

    def external_quota(request: Request):

        raw_key = extract_api_key_from_request(request)

        if not raw_key:

            raise HTTPException(401, 'Yêu cầu API Key qua Authorization: Bearer op_live_... hoặc X-API-Key')

        user = resolve_api_key(db, raw_key)

        return get_user_quota(db, user['id'])



    @app.post('/api/v1/publish')

    def external_publish(payload: ExternalPublishPayload, request: Request):

        raw_key = extract_api_key_from_request(request)

        if not raw_key:

            raise HTTPException(401, 'Yêu cầu API Key qua Authorization: Bearer op_live_... hoặc X-API-Key')

        user = resolve_api_key(db, raw_key)



        # 1. Enforce Quota: 10 posts/month limit for Free tier

        quota = validate_and_consume_quota(db, user['id'], count=1)



        # 2. Validate URL

        from app.tiktok_ingest import validate_tiktok_url

        url = validate_tiktok_url(payload.source_url)



        # 3. Find target destination

        with db.connect() as c:

            if payload.account_id:

                acc = c.execute(

                    select(accounts)

                    .where(accounts.c.id == payload.account_id, accounts.c.active == True)

                ).mappings().first()

            else:

                acc = c.execute(

                    select(accounts)

                    .where(accounts.c.provider == 'youtube', accounts.c.active == True)

                    .order_by(accounts.c.created_at)

                ).mappings().first()



        if not acc:

            raise HTTPException(400, 'Không tìm thấy kênh xuất bản (YouTube) đang kết nối.')



        # 4. Insert ingest task

        job_id = new_id()

        now = time.time()

        req_key = payload.request_key or f"n8n_{user['id'][:8]}_{job_id[:16]}"

        with db.begin() as c:

            c.execute(ingests.insert().values(

                id=job_id,

                user_id=user['id'],

                request_key=req_key,

                telegram_chat_id=payload.telegram_chat_id or '',

                telegram_message_id=payload.telegram_message_id,

                source_url=url,

                account_id=acc['id'],

                title=payload.title.strip(),

                description=payload.description.strip(),

                privacy=payload.privacy,

                shorts_mode=payload.shorts_mode,

                made_for_kids=payload.made_for_kids,

                status='pending',

                scheduled_at=now,

                created_at=now,

                updated_at=now

            ))



        return {

            'ok': True,

            'job_id': job_id,

            'request_key': req_key,

            'status': 'pending',

            'quota': {

                'tier': quota['tier'],

                'posts_used': quota['posts_used'],

                'posts_limit': quota['posts_limit'],

                'remaining': quota['remaining'],

                'cycle': quota['cycle']

            }

        }



    @app.get('/api/v1/jobs/{job_id}')

    def external_job_status(job_id: str, request: Request):

        raw_key = extract_api_key_from_request(request)

        if not raw_key:

            raise HTTPException(401, 'Yêu cầu API Key')

        user = resolve_api_key(db, raw_key)

        with db.connect() as c:

            job = c.execute(select(ingests).where(ingests.c.id == job_id)).mappings().first()

            if not job:

                raise HTTPException(404, 'Không tìm thấy tác vụ xuất bản.')

            post = c.execute(select(posts).where(posts.c.id == job['post_id'])).mappings().first() if job['post_id'] else None



        status = post['status'] if post else job['status']

        return {

            'job_id': job['id'],

            'status': status,

            'ingest_status': job['status'],

            'post_id': job['post_id'],

            'remote_url': post['remote_url'] if post else None,

            'error': post['error'] if post else job['error'],

            'terminal': status in ('submitted', 'failed', 'unknown', 'cancelled')

        }



    # --- STANDARD PUBLISHER ROUTES ---



    @app.get('/api/config')

    def config_info(request: Request):

        require_session(request)

        return {
            'providers': {p: api.available(p) for p in ('youtube', 'facebook', 'tiktok')},
            'max_upload_mb': s.max_upload_mb,
            'retention_days': s.retention_days,
            'database': 'Supabase / PostgreSQL' if db.dialect.name == 'postgresql' else 'SQLite — chế độ cục bộ',
            'worker': s.worker_enabled,
            'base_url': s.base_url
        }



    @app.get('/api/accounts')
    def list_accounts(request: Request, all: bool = False):
        session = require_session(request)
        user_id = session.get('user_id')
        with db.connect() as c:
            query = select(accounts.c.id, accounts.c.name, accounts.c.provider, accounts.c.external_id).where(accounts.c.active == True)
            if not (all and is_admin_session(session)):
                query = query.where(accounts.c.user_id == user_id)
            rows = c.execute(query.order_by(accounts.c.created_at)).mappings().all()
        return [dict(r) for r in rows]



    @app.delete('/api/accounts/{account_id}')

    @app.post('/api/accounts/{account_id}/disconnect')

    def disconnect(account_id: str, request: Request):

        mutation_auth(request)

        with db.begin() as c:

            active_job = c.execute(select(posts.c.id).where(posts.c.account_id == account_id,

                posts.c.status == 'posting')).first()

            if active_job:

                raise HTTPException(409, 'Đang đăng bài. Chờ tác vụ kết thúc trước khi ngắt kết nối.')

            c.execute(update(accounts).where(accounts.c.id == account_id).values(active=False, tokens=vault.encrypt({})))

            c.execute(update(posts).where(posts.c.account_id == account_id, posts.c.status == 'queued')

                .values(status='failed', error='Tài khoản đã ngắt kết nối.', updated_at=time.time()))

        return {'ok': True}



    @app.post('/api/oauth/{provider}/start')

    def start_oauth(provider: str, request: Request):

        session = mutation_auth(request)

        if not api.available(provider):

            raise HTTPException(400, 'Chưa cấu hình OAuth của nền tảng trong .env trên VPS.')

        state = secrets.token_urlsafe(32)

        verifier = secrets.token_urlsafe(64)

        with db.begin() as c:

            c.execute(oauth_states.insert().values(id=digest(state), session_id=session['id'],

                provider=provider, verifier=vault.encrypt(verifier), expires_at=time.time() + 600))

        return {'url': api.authorize_url(provider, state, verifier)}



    @app.get('/oauth/{provider}/callback')

    def oauth_callback(provider: str, request: Request, state: str = '', code: str = '', error: str = ''):

        session = require_session(request)

        with db.begin() as c:

            query = select(oauth_states).where(oauth_states.c.id == digest(state),

                oauth_states.c.provider == provider, oauth_states.c.session_id == session['id'],

                oauth_states.c.expires_at > time.time())

            if db.dialect.name == 'postgresql':

                query = query.with_for_update()

            row = c.execute(query).mappings().first()

            if not row:

                raise HTTPException(400, 'Yêu cầu kết nối đã hết hạn hoặc đã dùng. Bắt đầu lại từ ứng dụng.')

            result = c.execute(delete(oauth_states).where(oauth_states.c.id == row['id']))

            if result.rowcount != 1:

                raise HTTPException(400, 'Yêu cầu đã được sử dụng.')

        if error or not code:

            return RedirectResponse('/?connection=cancelled', status_code=303)

        found = api.exchange(provider, code, vault.decrypt(row['verifier']))

        with db.begin() as c:

            for account in found:

                old = c.execute(select(accounts.c.id).where(accounts.c.provider == provider,

                    accounts.c.external_id == account['external_id'])).first()

                values = {'name': account['name'], 'tokens': vault.encrypt(account['tokens']), 'active': True}

                if old:

                    c.execute(update(accounts).where(accounts.c.id == old.id).values(**values))

                else:

                    c.execute(accounts.insert().values(id=new_id(), user_id=session.get('user_id'), provider=provider,

                        external_id=account['external_id'], created_at=time.time(), **values))

        return RedirectResponse('/?connection=success', status_code=303)



    @app.post('/api/media')

    def upload_media(request: Request, file: UploadFile = File(...)):

        session = mutation_auth(request)

        if not file.filename or Path(file.filename).suffix.lower() != '.mp4':

            raise HTTPException(400, 'Bản đầu hỗ trợ video MP4.')

        if not upload_lock.acquire(blocking=False):

            raise HTTPException(429, 'Một video khác đang tải lên. Chờ hoàn tất rồi thử lại.')

        media_id = new_id()

        partial = s.data_dir / 'media' / f'{media_id}.part'

        target = partial.with_suffix('.mp4')

        try:

            existing = sum(p.stat().st_size for p in (s.data_dir / 'media').iterdir() if p.is_file())

            size = 0

            with partial.open('xb') as out:

                while chunk := file.file.read(1024 * 1024):

                    size += len(chunk)

                    if size > s.max_upload_mb * 1024**2 or existing + size > s.max_storage_mb * 1024**2:

                        raise HTTPException(413, 'Vượt giới hạn dung lượng video hoặc ổ lưu trữ.')

                    out.write(chunk)

            try:

                probe = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_entries',

                    'format=duration:stream=codec_type,width,height', '-of', 'json', str(partial)],

                    capture_output=True, timeout=20, check=True)

                info = json.loads(probe.stdout)

                video = next(v for v in info.get('streams', []) if v.get('codec_type') == 'video')

                duration = float(info['format']['duration'])

                if duration <= 0 or not video.get('width') or not video.get('height'):

                    raise ValueError('Invalid video')

            except (ValueError, KeyError, StopIteration, subprocess.SubprocessError):

                raise HTTPException(400, 'Không đọc được video MP4. Xuất lại file rồi tải lên.')

            except FileNotFoundError:

                raise HTTPException(503, 'VPS chưa cài ffprobe. Dùng bản Docker kèm theo.')

            partial.rename(target)

            values = {'id': media_id, 'user_id': session.get('user_id'), 'filename': Path(file.filename).name[:200],

                'path': str(target.resolve()), 'size': size, 'duration': duration,

                'width': video['width'], 'height': video['height'], 'created_at': time.time()}

            with db.begin() as c:

                c.execute(media.insert().values(**values))

            return {k: v for k, v in values.items() if k != 'path'}

        except Exception:

            partial.unlink(missing_ok=True)

            target.unlink(missing_ok=True)

            raise

        finally:

            upload_lock.release()

            file.file.close()



    @app.get('/api/media/{media_id}')

    def get_media(media_id: str, request: Request):

        session = require_session(request)

        with db.connect() as c:

            row = c.execute(select(media).where(media.c.id == media_id)).mappings().first()

        require_owner(session, row)

        if not row or not Path(row['path']).is_file():

            raise HTTPException(404, 'Video không còn được lưu.')

        return FileResponse(row['path'], media_type='video/mp4')



    @app.post('/api/posts')

    def create_posts(payload: CreatePost, request: Request):

        session = mutation_auth(request)

        user_id = session.get('user_id', 'usr_owner_default')

        target_ids = list(dict.fromkeys(payload.account_ids))

        now = time.time()

        if not payload.title.strip():

            raise HTTPException(400, 'Nhập tiêu đề.')

        if sum(len(t) + 1 for t in payload.tags) > 450 or any(len(t) > 80 for t in payload.tags):

            raise HTTPException(400, 'Danh sách tag quá dài.')

        if payload.scheduled_at and payload.scheduled_at.tzinfo is None:

            raise HTTPException(400, 'Thời gian hẹn phải kèm múi giờ.')

        when = payload.scheduled_at.timestamp() if payload.scheduled_at else now



        # Quota Validation: Check quota before queueing posts





        with db.begin() as c:

            existing = c.execute(select(posts.c.id).where(posts.c.batch_key == payload.batch_key, posts.c.user_id == user_id)).scalars().all()

            if existing:

                return {'ids': list(existing), 'deduplicated': True}

            destinations = c.execute(select(accounts).where(accounts.c.id.in_(target_ids),

                accounts.c.active == True)).mappings().all()

            if len(destinations) != len(target_ids):

                raise HTTPException(400, 'Tài khoản không tồn tại hoặc đã ngắt kết nối.')

            for destination in destinations:
                require_owner(session, destination)

            file = c.execute(select(media).where(media.c.id == payload.media_id)).mappings().first() if payload.media_id else None
            if payload.media_id:
                require_owner(session, file)

            if payload.media_id and (not file or not Path(file['path']).is_file()):

                raise HTTPException(400, 'Video không tồn tại. Tải lên lại.')

            for account in destinations:

                if account['provider'] == 'youtube':

                    if not file:

                        raise HTTPException(400, 'Chọn video cho YouTube.')

                    if payload.shorts and (file['duration'] > 180 or file['width'] > file['height']):

                        raise HTTPException(400, 'Chế độ Shorts yêu cầu video dọc/vuông và tối đa 3 phút. Hãy chọn "Video thường / dài" để đăng video này lên YouTube.')

            if payload.action == 'queue':
                validate_and_consume_quota(db, user_id, count=len(target_ids), connection=c)

            ids = []

            for account in destinations:

                post_id = new_id()

                ids.append(post_id)

                c.execute(posts.insert().values(id=post_id, user_id=user_id, batch_key=payload.batch_key,

                    account_id=account['id'], media_id=payload.media_id, title=payload.title.strip(),

                    description=payload.description, tags=json.dumps(payload.tags), privacy=payload.privacy,

                    made_for_kids=payload.made_for_kids, shorts=payload.shorts,

                    status='draft' if payload.action == 'draft' else 'queued', scheduled_at=when,

                    created_at=now, updated_at=now))

        return {'ids': ids, 'deduplicated': False}



    @app.exception_handler(IntegrityError)

    async def duplicate(request, exc):

        return JSONResponse({'detail': 'Yêu cầu bị trùng hoặc dữ liệu vừa thay đổi. Tải lại danh sách trước khi tiếp tục.'}, status_code=409)



    @app.get('/api/posts')

    def list_posts(request: Request):

        session = require_session(request)

        user_id = session.get('user_id')

        with db.connect() as c:

            query = select(posts, accounts.c.name.label('account_name'), accounts.c.provider)\
                .join(accounts, accounts.c.id == posts.c.account_id)

            if user_id and not is_admin_session(session):

                query = query.where(or_(posts.c.user_id == user_id, accounts.c.user_id == user_id))

            rows = c.execute(query.order_by(posts.c.created_at.desc()).limit(100)).mappings().all()

        return [dict(row) for row in rows]



    @app.delete('/api/posts/{post_id}')

    def delete_post(post_id: str, request: Request):

        session = mutation_auth(request)

        user_id = session.get('user_id')

        with db.begin() as c:

            post = c.execute(select(posts).where(posts.c.id == post_id)).mappings().first()

            if not post:

                raise HTTPException(404, 'Bài đăng không tồn tại.')

            require_owner(session, post)

            c.execute(delete(posts).where(posts.c.id == post_id))

        return {'ok': True}



    @app.post('/api/posts/{post_id}/{action}')

    def change_post(post_id: str, action: Literal['queue', 'cancel'], request: Request):

        session = mutation_auth(request)

        user_id = session.get('user_id', 'usr_owner_default')



        with db.begin() as c:

            allowed = ['draft', 'failed'] if action == 'queue' else ['draft', 'queued']

            row = c.execute(select(posts).where(posts.c.id == post_id)).mappings().first()

            if not row or row['status'] not in allowed:

                raise HTTPException(409, 'Bài đã thay đổi trạng thái hoặc không thể thực hiện thao tác này.')

            require_owner(session, row)
            account = c.execute(select(accounts).where(accounts.c.id == row['account_id'])).mappings().one()

            if action == 'queue' and not account['active']:

                raise HTTPException(400, 'Kết nối lại tài khoản trước khi đăng.')

            result = c.execute(update(posts).where(posts.c.id == post_id, posts.c.status.in_(allowed))

                .values(status='queued' if action == 'queue' else 'cancelled', error=None,

                    scheduled_at=time.time(), updated_at=time.time()))

            if result.rowcount != 1:

                raise HTTPException(409, 'Bài vừa được xử lý ở nơi khác.')
            if action == 'queue':
                validate_and_consume_quota(db, user_id, count=1, connection=c)

        return {'ok': True}



    from app.tasks import register_tasks
    register_tasks(app, db, require_session, mutation_auth, is_admin_session)

    root = Path(__file__).parent / 'static'


    @app.get('/api/admin/overview')
    def admin_overview(request: Request):
        session = require_admin(request)
        with db.connect() as c:
            total_users = c.execute(select(func.count(users.c.id))).scalar() or 0
            total_accounts = c.execute(select(func.count(accounts.c.id)).where(accounts.c.active == True)).scalar() or 0
            total_posts = c.execute(select(func.count(posts.c.id))).scalar() or 0
            queued_posts = c.execute(select(func.count(posts.c.id)).where(posts.c.status.in_(['queued', 'posting']))).scalar() or 0
            failed_posts = c.execute(select(func.count(posts.c.id)).where(posts.c.status == 'failed')).scalar() or 0
            delivered_posts = c.execute(select(func.count(posts.c.id)).where(posts.c.status == 'submitted')).scalar() or 0
        return {
            'total_users': total_users,
            'total_accounts': total_accounts,
            'total_posts': total_posts,
            'queued_posts': queued_posts,
            'failed_posts': failed_posts,
            'delivered_posts': delivered_posts,
            'worker_status': 'active' if s.worker_enabled else 'stopped'
        }

    @app.get('/api/admin/users')
    def admin_get_users(request: Request):
        session = require_admin(request)
        cycle = datetime.now(timezone.utc).strftime('%Y-%m')
        with db.connect() as c:
            u_rows = c.execute(select(users).order_by(users.c.created_at.desc())).mappings().all()
            q_rows = c.execute(select(usage_quotas).where(usage_quotas.c.cycle == cycle)).mappings().all()
            q_map = {q['user_id']: dict(q) for q in q_rows}
            acc_rows = c.execute(select(accounts.c.user_id, func.count(accounts.c.id).label('acc_count')).where(accounts.c.active == True).group_by(accounts.c.user_id)).mappings().all()
            acc_map = {a['user_id']: a['acc_count'] for a in acc_rows}
            result = []
            for u in u_rows:
                q = q_map.get(u['id'], {})
                result.append({
                    'id': u['id'],
                    'email': u['email'],
                    'name': u['name'],
                    'tier': u['tier'] or 'free',
                    'status': u['status'] or 'active',
                    'posts_limit': u['posts_limit'] or 10,
                    'posts_used': q.get('posts_used', 0),
                    'accounts_count': acc_map.get(u['id'], 0),
                    'created_at': u['created_at']
                })
        return {'users': result}

    @app.post('/api/admin/users/{target_user_id}/tier')
    def admin_update_user_tier(target_user_id: str, payload: AdminUserTierUpdate, request: Request):
        session = admin_mutation_auth(request)
        tier = payload.tier.lower().strip()
        if tier not in ('free', 'pro', 'agency'):
            raise HTTPException(400, 'Gói cước không hợp lệ (free, pro, agency).')
        posts_limit = max(1, min(9999999, int(payload.posts_limit)))
        now = time.time()
        with db.begin() as c:
            c.execute(update(users).where(users.c.id == target_user_id).values(
                tier=tier,
                posts_limit=posts_limit,
                updated_at=now
            ))
            cycle = datetime.now(timezone.utc).strftime('%Y-%m')
            c.execute(update(usage_quotas).where(
                and_(usage_quotas.c.user_id == target_user_id, usage_quotas.c.cycle == cycle)
            ).values(
                posts_limit=posts_limit,
                updated_at=now
            ))
        return {'ok': True, 'user_id': target_user_id, 'tier': tier, 'posts_limit': posts_limit}

    @app.post('/api/admin/users/{target_user_id}/status')
    def admin_update_user_status(target_user_id: str, payload: AdminUserStatusUpdate, request: Request):
        session = admin_mutation_auth(request)
        status = payload.status.lower().strip()
        if status not in ('active', 'suspended'):
            raise HTTPException(400, 'Trạng thái không hợp lệ (active, suspended).')
        with db.begin() as c:
            c.execute(update(users).where(users.c.id == target_user_id).values(
                status=status,
                updated_at=time.time()
            ))
        return {'ok': True, 'user_id': target_user_id, 'status': status}

    @app.get('/api/admin/posts')
    def admin_get_posts(request: Request):
        session = require_admin(request)
        with db.connect() as c:
            query = select(
                posts.c.id,
                posts.c.title,
                posts.c.status,
                posts.c.remote_id, posts.c.remote_url,
                posts.c.error,
                posts.c.created_at,
                posts.c.scheduled_at,
                posts.c.user_id,
                accounts.c.name.label('account_name'),
                accounts.c.provider,
                users.c.name.label('user_name'),
                users.c.email.label('user_email')
            ).select_from(
                posts.outerjoin(accounts, accounts.c.id == posts.c.account_id)
                     .outerjoin(users, users.c.id == posts.c.user_id)
            ).order_by(posts.c.created_at.desc()).limit(150)
            rows = c.execute(query).mappings().all()
        return {'posts': [dict(r) for r in rows]}

    app.mount('/static', StaticFiles(directory=root), name='static')



    @app.get('/')
    def index():
        return FileResponse(root / 'index.html')

    @app.api_route('/privacy', methods=['GET', 'HEAD'])
    def privacy():
        return FileResponse(root / 'privacy.html')

    @app.api_route('/terms', methods=['GET', 'HEAD'])
    def terms():
        return FileResponse(root / 'terms.html')

    @app.api_route('/tiktokcqeNphwcQ94DoltOcdmjS5LgQgfmyu6j.txt', methods=['GET', 'HEAD'])
    @app.api_route('/tiktok-developers-site-verification.txt', methods=['GET', 'HEAD'])
    @app.api_route('/terms/tiktok-developers-site-verification.txt', methods=['GET', 'HEAD'])
    @app.api_route('/privacy/tiktok-developers-site-verification.txt', methods=['GET', 'HEAD'])
    def tiktok_verify_exact():
        return PlainTextResponse("tiktok-developers-site-verification=cqeNphwcQ94DoltOcdmjS5LgQgfmyu6j")

    @app.api_route('/tiktok{token}.txt', methods=['GET', 'HEAD'])
    @app.api_route('/terms/tiktok{token}.txt', methods=['GET', 'HEAD'])
    @app.api_route('/privacy/tiktok{token}.txt', methods=['GET', 'HEAD'])
    def tiktok_verify_prefix(token: str):
        return PlainTextResponse(f"tiktok-developers-site-verification={token}")

    @app.api_route('/tiktok-developers-site-verification.html', methods=['GET', 'HEAD'])
    def tiktok_verify_standard_html():
        return HTMLResponse("tiktok-developers-site-verification=cqeNphwcQ94DoltOcdmjS5LgQgfmyu6j")

    @app.api_route('/tiktok-developers-site-verification={token}', methods=['GET', 'HEAD'])
    def tiktok_verify(token: str):
        return PlainTextResponse(f"tiktok-developers-site-verification={token}")

    @app.api_route('/tiktok-developers-site-verification={token}.txt', methods=['GET', 'HEAD'])
    def tiktok_verify_txt(token: str):
        return PlainTextResponse(f"tiktok-developers-site-verification={token}")

    @app.api_route('/tiktok-developers-site-verification={token}.html', methods=['GET', 'HEAD'])
    def tiktok_verify_html(token: str):
        return HTMLResponse(f"tiktok-developers-site-verification={token}")



    return app

