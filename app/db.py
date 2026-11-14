import time
import uuid
from sqlalchemy import (create_engine, MetaData, Table, Column, String, Text,
                        Integer, Float, Boolean, ForeignKey, UniqueConstraint, Index, select, update, inspect)

metadata = MetaData()

# Multi-tenant Users
users = Table('sp_users', metadata,
    Column('id', String(36), primary_key=True),
    Column('email', String(255), nullable=False, unique=True),
    Column('password_hash', String(255), nullable=False),
    Column('name', String(100)),
    Column('role', String(20), nullable=False, default='user', server_default='user'),
    Column('tier', String(20), nullable=False, default='free'), # free, pro, agency
    Column('status', String(20), nullable=False, default='active'), # active, suspended
    Column('posts_limit', Integer, nullable=False, default=10), # 10 for free, 999999 for pro/agency
    Column('created_at', Float, nullable=False),
    Column('updated_at', Float, nullable=False))
Index('sp_users_email_idx', users.c.email)

# API Keys for n8n, Make, and automated external publishing
api_keys = Table('sp_api_keys', metadata,
    Column('id', String(36), primary_key=True),
    Column('user_id', String(36), ForeignKey('sp_users.id'), nullable=False),
    Column('key_hash', String(64), nullable=False, unique=True),
    Column('key_prefix', String(24), nullable=False),
    Column('name', String(100), nullable=False, default='n8n Integration'),
    Column('active', Boolean, nullable=False, default=True),
    Column('last_used_at', Float),
    Column('created_at', Float, nullable=False))
Index('sp_api_keys_user_idx', api_keys.c.user_id)

# Monthly Quota tracking (10 posts/month for Free tier)
usage_quotas = Table('sp_usage_quotas', metadata,
    Column('id', String(36), primary_key=True),
    Column('user_id', String(36), ForeignKey('sp_users.id'), nullable=False),
    Column('cycle', String(7), nullable=False), # e.g. '2026-11'
    Column('posts_used', Integer, nullable=False, default=0),
    Column('posts_limit', Integer, nullable=False, default=10),
    Column('updated_at', Float, nullable=False),
    UniqueConstraint('user_id', 'cycle'))
Index('sp_usage_quotas_user_cycle_idx', usage_quotas.c.user_id, usage_quotas.c.cycle)

accounts = Table('sp_accounts', metadata,
    Column('id', String(36), primary_key=True),
    Column('user_id', String(36), ForeignKey('sp_users.id')),
    Column('provider', String(20), nullable=False),
    Column('external_id', String(128), nullable=False),
    Column('name', String(300), nullable=False),
    Column('tokens', Text, nullable=False),
    Column('active', Boolean, nullable=False, default=True),
    Column('created_at', Float, nullable=False),
    UniqueConstraint('provider', 'external_id'))

media = Table('sp_media', metadata,
    Column('id', String(36), primary_key=True),
    Column('user_id', String(36), ForeignKey('sp_users.id')),
    Column('filename', String(200), nullable=False),
    Column('path', Text, nullable=False),
    Column('size', Integer, nullable=False),
    Column('duration', Float, nullable=False),
    Column('width', Integer, nullable=False),
    Column('height', Integer, nullable=False),
    Column('created_at', Float, nullable=False))

posts = Table('sp_posts', metadata,
    Column('id', String(36), primary_key=True),
    Column('user_id', String(36), ForeignKey('sp_users.id')),
    Column('batch_key', String(100), nullable=False),
    Column('account_id', String(36), ForeignKey('sp_accounts.id'), nullable=False),
    Column('media_id', String(36), ForeignKey('sp_media.id')),
    Column('title', String(100), nullable=False),
    Column('description', Text, nullable=False),
    Column('tags', Text, nullable=False),
    Column('privacy', String(20), nullable=False),
    Column('made_for_kids', Boolean, nullable=False, default=False),
    Column('shorts', Boolean, nullable=False, default=False),
    Column('status', String(30), nullable=False),
    Column('scheduled_at', Float, nullable=False),
    Column('created_at', Float, nullable=False),
    Column('updated_at', Float, nullable=False),
    Column('remote_id', String(150)),
    Column('remote_url', Text),
    Column('error', Text),
    Column('lease_until', Float),
    UniqueConstraint('batch_key', 'account_id'))
Index('sp_posts_due_idx', posts.c.status, posts.c.scheduled_at)

ingests = Table('sp_ingests', metadata,
    Column('id', String(36), primary_key=True),
    Column('user_id', String(36), ForeignKey('sp_users.id')),
    Column('request_key', String(100), nullable=False, unique=True),
    Column('telegram_chat_id', String(32), nullable=False),
    Column('telegram_message_id', String(32)),
    Column('privacy', String(20), default='private'),
    Column('shorts_mode', String(20), default='auto'),
    Column('target_platform', String(20), default='youtube'),
    Column('notified_at', Float),
    Column('source_url', Text, nullable=False),
    Column('account_id', String(36), ForeignKey('sp_accounts.id'), nullable=False),
    Column('title', String(100), nullable=False),
    Column('description', Text, nullable=False),
    Column('made_for_kids', Boolean, nullable=False),
    Column('status', String(30), nullable=False),
    Column('scheduled_at', Float, nullable=False),
    Column('created_at', Float, nullable=False),
    Column('updated_at', Float, nullable=False),
    Column('post_id', String(36)),
    Column('error', Text),
    Column('lease_until', Float))
Index('sp_ingests_due_idx', ingests.c.status, ingests.c.created_at)

sessions = Table('sp_sessions', metadata,
    Column('id', String(64), primary_key=True),
    Column('user_id', String(36), ForeignKey('sp_users.id')),
    Column('csrf', String(64), nullable=False),
    Column('expires_at', Float, nullable=False))

oauth_states = Table('sp_oauth_states', metadata,
    Column('id', String(64), primary_key=True),
    Column('session_id', String(64), nullable=False),
    Column('provider', String(20), nullable=False),
    Column('verifier', Text, nullable=False),
    Column('expires_at', Float, nullable=False))


def make_engine(url):
    if url.startswith('sqlite'):
        return create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30})
    return create_engine(url, pool_size=2, max_overflow=1, pool_pre_ping=True,
                         connect_args={'prepare_threshold': None})


def new_id():
    return str(uuid.uuid4())


def initialize(engine, admin_password_hash=None):
    inspector = inspect(engine)
    role_migration = 'sp_users' not in inspector.get_table_names() or 'role' not in {col['name'] for col in inspector.get_columns('sp_users')}
    if 'sp_users' in inspector.get_table_names() and role_migration:
        with engine.begin() as c:
            c.exec_driver_sql("ALTER TABLE sp_users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'")
    tp_migration = 'sp_ingests' in inspector.get_table_names() and 'target_platform' not in {col['name'] for col in inspector.get_columns('sp_ingests')}
    if 'sp_ingests' in inspector.get_table_names() and tp_migration:
        with engine.begin() as c:
            c.exec_driver_sql("ALTER TABLE sp_ingests ADD COLUMN target_platform VARCHAR(20) NOT NULL DEFAULT 'youtube'")
    metadata.create_all(engine)
    if engine.dialect.name == 'postgresql':
        with engine.begin() as c:
            # Multi-tenant migration: safely add user_id column to existing tables
            for tbl in ('sp_accounts', 'sp_posts', 'sp_media', 'sp_ingests', 'sp_sessions'):
                c.exec_driver_sql(f'ALTER TABLE public.{tbl} ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)')
            c.exec_driver_sql('ALTER TABLE public.sp_users ADD COLUMN IF NOT EXISTS posts_limit INTEGER DEFAULT 10')

            for t in metadata.sorted_tables:
                c.exec_driver_sql(f'ALTER TABLE public.{t.name} ENABLE ROW LEVEL SECURITY')
                c.exec_driver_sql(f'REVOKE ALL ON public.{t.name} FROM PUBLIC')
                for role in ('anon', 'authenticated'):
                    exists = c.exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).first()
                    if exists:
                        c.exec_driver_sql(f'REVOKE ALL ON public.{t.name} FROM {role}')

    # Seed initial Admin owner if sp_users is empty
    with engine.begin() as c:
        admin_row = c.execute(select(users).where(users.c.email == 'admin@toomi.vn')).mappings().first()
        admin_id = admin_row['id'] if admin_row else 'usr_owner_default'
        now = time.time()
        if not admin_row:
            c.execute(users.insert().values(
                id=admin_id,
                email='admin@toomi.vn',
                password_hash=admin_password_hash or '',
                name='OmniPublish Administrator',
                role='superadmin',
                tier='agency',
                status='active',
                posts_limit=999999,
                created_at=now,
                updated_at=now
            ))
        elif admin_password_hash and admin_row['password_hash'] != admin_password_hash:
            c.execute(update(users).where(users.c.id == admin_id).values(password_hash=admin_password_hash, updated_at=now))

        # One-time conversion authorized by the owner; never regrant on every boot.
        if role_migration:
            c.execute(update(users).where(users.c.id == admin_id).values(role='superadmin'))
            c.execute(update(users).where(users.c.email == 'khuongtran227@gmail.com').values(role='superadmin'))

        # Assign existing unassigned rows to admin owner
        for tbl in (accounts, posts, media, ingests, sessions):
            c.execute(update(tbl).where(tbl.c.user_id.is_(None)).values(user_id=admin_id))


def claim_post(engine):
    with engine.begin() as c:
        query = select(posts.c.id).where(posts.c.status == 'queued',
            posts.c.scheduled_at <= time.time()).order_by(posts.c.scheduled_at).limit(1)
        if engine.dialect.name == 'postgresql':
            query = query.with_for_update(skip_locked=True)
        row = c.execute(query).first()
        if not row:
            return None
        result = c.execute(update(posts).where(posts.c.id == row.id,
            posts.c.status == 'queued').values(status='posting',
            updated_at=time.time(), lease_until=time.time() + 180))
        return row.id if result.rowcount == 1 else None


def claim_ingest(engine):
    """Atomically acquire one pending ingestion. Only the queue owner may download."""
    with engine.begin() as c:
        query = select(ingests.c.id).where(ingests.c.status == 'pending').order_by(
            ingests.c.created_at).limit(1)
        if engine.dialect.name == 'postgresql':
            query = query.with_for_update(skip_locked=True)
        row = c.execute(query).first()
        if not row:
            return None
        now = time.time()
        changed = c.execute(update(ingests).where(
            ingests.c.id == row.id, ingests.c.status == 'pending'
        ).values(status='downloading', updated_at=now, lease_until=now + 300))
        return row.id if changed.rowcount == 1 else None
