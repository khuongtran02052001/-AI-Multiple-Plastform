"""Read-only task projection plus cancellation of work not yet claimed."""
import time
from fastapi import HTTPException, Request
from sqlalchemy import select, update
from app.db import ingests, posts, accounts


def register_tasks(app, engine, require_session, mutation_auth, is_admin):
    def visible(row, session):
        return row['user_id'] == session['user_id'] or is_admin(session)

    @app.get('/api/tasks')
    def list_tasks(request: Request, limit: int = 50, offset: int = 0):
        session = require_session(request)
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(400, 'Phân trang không hợp lệ.')
        admin = is_admin(session)
        with engine.connect() as c:
            # Query ownership BEFORE pagination; never expose tokens or Telegram credentials.
            iq = select(ingests)
            pq = select(posts)
            if not admin:
                iq = iq.where(ingests.c.user_id == session['user_id'])
                pq = pq.where(posts.c.user_id == session['user_id'])
            jobs = c.execute(iq.order_by(ingests.c.created_at.desc()).limit(limit+offset+1)).mappings().all()
            linked = select(ingests.c.post_id).where(ingests.c.post_id.is_not(None))
            direct = c.execute(pq.where(~posts.c.id.in_(linked)).order_by(posts.c.created_at.desc()).limit(limit+offset+1)).mappings().all()
            rows = []
            for job in jobs:
                post = c.execute(select(posts).where(posts.c.id == job['post_id'])).mappings().first() if job['post_id'] else None
                # Never project a linked record owned by a different tenant.
                if post and not admin and post['user_id'] != session['user_id']:
                    post = None
                rows.append(project(job, post, 'ingest'))
            rows.extend(project(p, p, 'post') for p in direct)
        rows.sort(key=lambda r: r['created_at'], reverse=True)
        return {'tasks': rows[offset:offset+limit], 'has_more': len(rows) > offset+limit}

    @app.post('/api/tasks/{kind}/{task_id}/cancel')
    def cancel_task(kind: str, task_id: str, request: Request):
        session = mutation_auth(request)
        table = ingests if kind == 'ingest' else posts if kind == 'post' else None
        if table is None:
            raise HTTPException(404, 'Không tìm thấy tác vụ.')
        with engine.begin() as c:
            query = select(table).where(table.c.id == task_id)
            if c.dialect.name == 'postgresql': query = query.with_for_update()
            row = c.execute(query).mappings().first()
            if not row or not visible(row, session):
                raise HTTPException(404, 'Không tìm thấy tác vụ.')
            if table is ingests and row['post_id']:
                changed = c.execute(update(posts).where(posts.c.id == row['post_id'],
                    posts.c.user_id == row['user_id'], posts.c.status == 'queued')
                    .values(status='cancelled', updated_at=time.time()))
                if changed.rowcount != 1: raise HTTPException(409, 'Tác vụ đã bắt đầu hoặc kết thúc; không thể hủy.')
                c.execute(update(ingests).where(ingests.c.id == task_id).values(status='cancelled', updated_at=time.time()))
            else:
                allowed = ('pending',) if table is ingests else ('draft','queued')
                changed = c.execute(update(table).where(table.c.id == task_id, table.c.status.in_(allowed))
                    .values(status='cancelled', updated_at=time.time()))
                if changed.rowcount != 1: raise HTTPException(409, 'Tác vụ đã bắt đầu hoặc kết thúc; không thể hủy.')
        return {'ok': True}


def project(job, post, kind):
    status = post['status'] if post else job['status']
    return {'id': job['id'], 'kind': kind, 'post_id': post['id'] if post else None,
            'title': (post['title'] if post else job['title']) or 'Video đang xử lý',
            'status': status, 'created_at': job['created_at'],
            'updated_at': post['updated_at'] if post else job['updated_at'],
            'source_url': job['source_url'] if kind == 'ingest' else None,
            'remote_url': post['remote_url'] if post else None,
            'privacy': post['privacy'] if post else job['privacy'],
            'error': post['error'] if post else job['error'],
            'can_cancel': status in ('pending','queued','draft'),
            'can_retry': bool(post and status == 'failed')}
