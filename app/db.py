import time
import uuid
from sqlalchemy import (create_engine, MetaData, Table, Column, String, Text,
                        Integer, Float, Boolean, ForeignKey, UniqueConstraint, Index)

metadata = MetaData()

accounts = Table('sp_accounts', metadata,
    Column('id', String(36), primary_key=True),
    Column('provider', String(20), nullable=False),
    Column('external_id', String(128), nullable=False),
    Column('name', String(300), nullable=False),
    Column('tokens', Text, nullable=False),
    Column('active', Boolean, nullable=False, default=True),
    Column('created_at', Float, nullable=False),
    UniqueConstraint('provider', 'external_id'))

media = Table('sp_media', metadata,
    Column('id', String(36), primary_key=True),
    Column('filename', String(200), nullable=False),
    Column('path', Text, nullable=False),
    Column('size', Integer, nullable=False),
    Column('duration', Float, nullable=False),
    Column('width', Integer, nullable=False),
    Column('height', Integer, nullable=False),
    Column('created_at', Float, nullable=False))

posts = Table('sp_posts', metadata,
    Column('id', String(36), primary_key=True),
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
    Column('request_key', String(100), nullable=False, unique=True),
    Column('telegram_chat_id', String(32), nullable=False),
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


def initialize(engine):
    metadata.create_all(engine)
    if engine.dialect.name == 'postgresql':
        # No browser/Data API access. The VPS uses a backend database role.
        with engine.begin() as c:
            for t in metadata.sorted_tables:
                c.exec_driver_sql(f'ALTER TABLE public.{t.name} ENABLE ROW LEVEL SECURITY')
                c.exec_driver_sql(f'REVOKE ALL ON public.{t.name} FROM PUBLIC')
                for role in ('anon', 'authenticated'):
                    exists = c.exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).first()
                    if exists:
                        c.exec_driver_sql(f'REVOKE ALL ON public.{t.name} FROM {role}')


def claim_post(engine):
    from sqlalchemy import select, update
    with engine.begin() as c:
        query = select(posts.c.id).where(posts.c.status == 'queued',
            posts.c.scheduled_at <= time.time()).order_by(posts.c.scheduled_at).limit(1)
        if engine.dialect.name == 'postgresql':
            query = query.with_for_update(skip_locked=True)
        row = c.execute(query).first()
        if not row:
            return None
        # Compare-and-set also protects the SQLite development backend.
        result = c.execute(update(posts).where(posts.c.id == row.id,
            posts.c.status == 'queued').values(status='posting',
            updated_at=time.time(), lease_until=time.time() + 180))
        return row.id if result.rowcount == 1 else None

def claim_ingest(engine):
    """Atomically acquire one pending ingestion. Only the queue owner may download."""
    from sqlalchemy import select, update
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
