"""API Key and Multi-tenant Authentication for Publisher integrations (n8n, Make, scripts).
"""
import secrets
import time
from fastapi import HTTPException, Request
from sqlalchemy import select, update
from app.db import users, api_keys, new_id
from app.security import digest


def generate_api_key(engine, user_id: str, name: str = 'n8n Integration') -> tuple[str, dict]:
    """Generate a high-entropy secret key and store only its SHA-256 hash."""
    random_part = secrets.token_hex(20)
    raw_key = f"op_live_{random_part}"
    key_prefix = f"op_live_{random_part[:6]}...{random_part[-4:]}"
    key_hash = digest(raw_key)
    key_id = new_id()
    now = time.time()

    with engine.begin() as c:
        # Check user exists
        u = c.execute(select(users).where(users.c.id == user_id)).mappings().first()
        if not u:
            raise HTTPException(404, 'Người dùng không tồn tại.')

        c.execute(api_keys.insert().values(
            id=key_id,
            user_id=user_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name[:100],
            active=True,
            last_used_at=None,
            created_at=now
        ))

    return raw_key, {
        'id': key_id,
        'user_id': user_id,
        'key_prefix': key_prefix,
        'name': name,
        'created_at': now,
        'last_used_at': None,
        'active': True
    }


def resolve_api_key(engine, raw_key: str) -> dict:
    """Validate raw API Key, update last_used_at, and return the associated user profile."""
    if not raw_key or not isinstance(raw_key, str) or not raw_key.startswith('op_live_'):
        raise HTTPException(401, 'API Key không hợp lệ. Khóa phải bắt đầu bằng op_live_.')

    key_hash = digest(raw_key.strip())
    now = time.time()

    with engine.begin() as c:
        row = c.execute(
            select(
                api_keys.c.id.label('key_id'),
                api_keys.c.user_id,
                api_keys.c.active.label('key_active'),
                users.c.email,
                users.c.name,
                users.c.tier,
                users.c.status.label('user_status'),
                users.c.posts_limit
            )
            .select_from(api_keys.join(users, api_keys.c.user_id == users.c.id))
            .where(api_keys.c.key_hash == key_hash)
        ).mappings().first()

        if not row:
            raise HTTPException(401, 'API Key không tồn tại hoặc đã bị thu hồi.')
        if not row['key_active']:
            raise HTTPException(403, 'API Key đã bị vô hiệu hóa.')
        if row['user_status'] != 'active':
            raise HTTPException(403, 'Tài khoản người dùng đã bị khóa hoặc tạm dừng.')

        # Update last_used_at
        c.execute(
            update(api_keys)
            .where(api_keys.c.id == row['key_id'])
            .values(last_used_at=now)
        )

    return {
        'id': row['user_id'],
        'email': row['email'],
        'name': row['name'],
        'tier': row['tier'],
        'posts_limit': row['posts_limit'] if row['posts_limit'] is not None else (10 if row['tier'] == 'free' else 999999),
        'key_id': row['key_id']
    }


def extract_api_key_from_request(request: Request) -> str | None:
    """Extract API Key from Authorization Bearer or X-API-Key header."""
    auth_header = request.headers.get('Authorization', '').strip()
    if auth_header.startswith('Bearer '):
        token = auth_header[7:].strip()
        if token.startswith('op_live_'):
            return token

    x_key = request.headers.get('X-API-Key', '').strip()
    if x_key.startswith('op_live_'):
        return x_key

    return None


def list_user_api_keys(engine, user_id: str) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(
            select(api_keys)
            .where(api_keys.c.user_id == user_id)
            .order_by(api_keys.c.created_at.desc())
        ).mappings().all()
    return [
        {
            'id': r['id'],
            'name': r['name'],
            'key_prefix': r['key_prefix'],
            'created_at': r['created_at'],
            'last_used_at': r['last_used_at'],
            'active': r['active']
        }
        for r in rows
    ]


def revoke_user_api_key(engine, user_id: str, key_id: str) -> bool:
    with engine.begin() as c:
        res = c.execute(
            update(api_keys)
            .where(api_keys.c.id == key_id, api_keys.c.user_id == user_id)
            .values(active=False)
        )
        return res.rowcount > 0
