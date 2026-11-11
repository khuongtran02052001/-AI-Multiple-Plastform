import json
import secrets
import subprocess
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, update, delete, func
from sqlalchemy.exc import IntegrityError
from app.config import settings as default_settings
from app.db import make_engine, initialize, accounts, media, posts, sessions, oauth_states, new_id
from app.security import Vault, verify_password, digest
from app.providers import Providers, PublishError
from app.worker import loop
from app.automation import register_automation


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=512)


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
        initialize(db)
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

    app = FastAPI(title='khuoqtd Publisher', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db = db
    app.state.vault = vault
    register_automation(app, db, s)

    def require_session(request):
        raw = request.cookies.get('sp_session', '')
        if not raw:
            raise HTTPException(401, 'Đăng nhập để tiếp tục.')
        with db.connect() as c:
            row = c.execute(select(sessions).where(sessions.c.id == digest(raw),
                sessions.c.expires_at > time.time())).mappings().first()
        if not row:
            raise HTTPException(401, 'Phiên đăng nhập đã hết hạn.')
        return dict(row)

    def mutation_auth(request):
        session = require_session(request)
        if request.headers.get('origin') != s.base_url:
            raise HTTPException(403, 'Origin không hợp lệ.')
        if not secrets.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):
            raise HTTPException(403, 'CSRF token không hợp lệ.')
        return session

    @app.middleware('http')
    async def headers(request, call_next):
        if request.method in ('POST', 'PUT', 'PATCH') and request.url.path != '/api/media':
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
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
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
            # Keep rate-limit memory bounded. Behind the bundled proxy the limit is shared.
            for key in list(attempts):
                while attempts[key] and attempts[key][0] < now - 900:
                    attempts[key].popleft()
                if not attempts[key]:
                    del attempts[key]
            if len(attempts[ip]) >= 10:
                raise HTTPException(429, 'Quá nhiều lần đăng nhập. Thử lại sau 15 phút.')
            attempts[ip].append(now)
        if not verify_password(payload.password, s.admin_password_hash):
            raise HTTPException(401, 'Mật khẩu không đúng.')
        raw = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        with db.begin() as c:
            c.execute(sessions.insert().values(id=digest(raw), csrf=csrf, expires_at=time.time() + 28800))
        response = JSONResponse({'csrf': csrf})
        response.set_cookie('sp_session', raw, httponly=True, secure=s.secure,
                            samesite='lax', max_age=28800, path='/')
        return response

    @app.get('/api/session')
    def session_info(request: Request):
        session = require_session(request)
        return {'csrf': session['csrf']}

    @app.post('/api/logout')
    def logout(request: Request):
        session = mutation_auth(request)
        with db.begin() as c:
            c.execute(delete(sessions).where(sessions.c.id == session['id']))
            c.execute(delete(oauth_states).where(oauth_states.c.session_id == session['id']))
        response = JSONResponse({'ok': True})
        response.delete_cookie('sp_session')
        return response

    @app.get('/api/config')
    def config_info(request: Request):
        require_session(request)
        return {'providers': {p: api.available(p) for p in ('youtube', 'facebook')},
                'max_upload_mb': s.max_upload_mb, 'retention_days': s.retention_days,
                'database': 'Supabase / PostgreSQL' if db.dialect.name == 'postgresql' else 'SQLite — chế độ cục bộ',
                'worker': s.worker_enabled, 'base_url': s.base_url}

    @app.get('/api/accounts')
    def list_accounts(request: Request):
        require_session(request)
        with db.connect() as c:
            rows = c.execute(select(accounts.c.id, accounts.c.name, accounts.c.provider,
                accounts.c.external_id).where(accounts.c.active == True).order_by(accounts.c.created_at)).mappings().all()
        return [dict(r) for r in rows]

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
                    c.execute(accounts.insert().values(id=new_id(), provider=provider,
                        external_id=account['external_id'], created_at=time.time(), **values))
        return RedirectResponse('/?connection=success', status_code=303)

    @app.post('/api/media')
    def upload_media(request: Request, file: UploadFile = File(...)):
        mutation_auth(request)
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
            values = {'id': media_id, 'filename': Path(file.filename).name[:200],
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
        require_session(request)
        with db.connect() as c:
            row = c.execute(select(media).where(media.c.id == media_id)).mappings().first()
        if not row or not Path(row['path']).is_file():
            raise HTTPException(404, 'Video không còn được lưu.')
        return FileResponse(row['path'], media_type='video/mp4')

    @app.post('/api/posts')
    def create_posts(payload: CreatePost, request: Request):
        mutation_auth(request)
        target_ids = list(dict.fromkeys(payload.account_ids))
        now = time.time()
        if not payload.title.strip():
            raise HTTPException(400, 'Nhập tiêu đề.')
        if sum(len(t) + 1 for t in payload.tags) > 450 or any(len(t) > 80 for t in payload.tags):
            raise HTTPException(400, 'Danh sách tag quá dài.')
        if payload.scheduled_at and payload.scheduled_at.tzinfo is None:
            raise HTTPException(400, 'Thời gian hẹn phải kèm múi giờ.')
        when = payload.scheduled_at.timestamp() if payload.scheduled_at else now
        with db.begin() as c:
            existing = c.execute(select(posts.c.id).where(posts.c.batch_key == payload.batch_key)).scalars().all()
            if existing:
                return {'ids': list(existing), 'deduplicated': True}
            destinations = c.execute(select(accounts).where(accounts.c.id.in_(target_ids),
                accounts.c.active == True)).mappings().all()
            if len(destinations) != len(target_ids):
                raise HTTPException(400, 'Tài khoản không tồn tại hoặc đã ngắt kết nối.')
            file = c.execute(select(media).where(media.c.id == payload.media_id)).mappings().first() if payload.media_id else None
            if payload.media_id and (not file or not Path(file['path']).is_file()):
                raise HTTPException(400, 'Video không tồn tại. Tải lên lại.')
            for account in destinations:
                if account['provider'] == 'youtube':
                    if not file:
                        raise HTTPException(400, 'Chọn video cho YouTube.')
                    if payload.shorts and (file['duration'] > 180 or file['width'] > file['height']):
                        raise HTTPException(400, 'Chế độ Shorts cần video vuông/dọc và không quá 180 giây.')
            ids = []
            for account in destinations:
                post_id = new_id()
                ids.append(post_id)
                c.execute(posts.insert().values(id=post_id, batch_key=payload.batch_key,
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
        require_session(request)
        with db.connect() as c:
            rows = c.execute(select(posts, accounts.c.name.label('account_name'), accounts.c.provider)
                .join(accounts, accounts.c.id == posts.c.account_id).order_by(posts.c.created_at.desc()).limit(100)).mappings().all()
        return [dict(row) for row in rows]

    @app.post('/api/posts/{post_id}/{action}')
    def change_post(post_id: str, action: Literal['queue', 'cancel'], request: Request):
        mutation_auth(request)
        with db.begin() as c:
            # No automatic or manual retry for unknown: the user must inspect the platform first.
            allowed = ['draft', 'failed'] if action == 'queue' else ['draft', 'queued']
            row = c.execute(select(posts).where(posts.c.id == post_id)).mappings().first()
            if not row or row['status'] not in allowed:
                raise HTTPException(409, 'Bài đã thay đổi trạng thái hoặc không thể thực hiện thao tác này.')
            account = c.execute(select(accounts).where(accounts.c.id == row['account_id'])).mappings().one()
            if action == 'queue' and not account['active']:
                raise HTTPException(400, 'Kết nối lại tài khoản trước khi đăng.')
            result = c.execute(update(posts).where(posts.c.id == post_id, posts.c.status.in_(allowed))
                .values(status='queued' if action == 'queue' else 'cancelled', error=None,
                    scheduled_at=time.time(), updated_at=time.time()))
            if result.rowcount != 1:
                raise HTTPException(409, 'Bài vừa được xử lý ở nơi khác.')
        return {'ok': True}

    root = Path(__file__).parent / 'static'
    app.mount('/static', StaticFiles(directory=root), name='static')

    @app.get('/')
    def index():
        return FileResponse(root / 'index.html')

    return app
