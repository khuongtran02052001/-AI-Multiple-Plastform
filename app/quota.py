"""Quota and billing cycle management for multi-tenant publishing.

Enforces 10 posts/month limit for Free tier, with instant upgrades for Pro/Agency tiers.
"""
from datetime import datetime, timezone
import time
from fastapi import HTTPException
from sqlalchemy import select, update
from app.db import users, usage_quotas, new_id


def get_current_cycle() -> str:
    """Return calendar month cycle string YYYY-MM in UTC."""
    return datetime.now(timezone.utc).strftime('%Y-%m')


def get_user_quota(engine, user_id: str) -> dict:
    """Fetch or initialize the current billing cycle quota for a given user."""
    cycle = get_current_cycle()
    now = time.time()
    with engine.begin() as c:
        u = c.execute(select(users).where(users.c.id == user_id)).mappings().first()
        if not u:
            raise HTTPException(404, 'Không tìm thấy tài khoản người dùng.')
        
        tier = u['tier']
        user_limit = u['posts_limit'] if u['posts_limit'] is not None else (10 if tier == 'free' else 999999)

        q = c.execute(
            select(usage_quotas).where(
                usage_quotas.c.user_id == user_id,
                usage_quotas.c.cycle == cycle
            )
        ).mappings().first()

        if not q:
            quota_id = new_id()
            c.execute(usage_quotas.insert().values(
                id=quota_id,
                user_id=user_id,
                cycle=cycle,
                posts_used=0,
                posts_limit=user_limit,
                updated_at=now
            ))
            posts_used = 0
            posts_limit = user_limit
        else:
            posts_used = q['posts_used']
            posts_limit = q['posts_limit']
            # Sync user limit if tier upgraded
            if user_limit != posts_limit:
                c.execute(
                    update(usage_quotas)
                    .where(usage_quotas.c.id == q['id'])
                    .values(posts_limit=user_limit, updated_at=now)
                )
                posts_limit = user_limit

    is_unlimited = (tier in ('pro', 'agency')) or (posts_limit >= 999999)
    remaining = max(0, posts_limit - posts_used) if not is_unlimited else 999999

    return {
        'user_id': user_id,
        'cycle': cycle,
        'tier': tier,
        'posts_used': posts_used,
        'posts_limit': posts_limit,
        'remaining': remaining,
        'is_unlimited': is_unlimited,
        'upgrade_url': '/#pricing'
    }


def validate_and_consume_quota(engine, user_id: str, count: int = 1) -> dict:
    """Atomic quota check & consumption.

    Raises HTTP 429 if limit is reached on Free tier.
    """
    if count <= 0:
        return get_user_quota(engine, user_id)

    cycle = get_current_cycle()
    now = time.time()

    with engine.begin() as c:
        u = c.execute(select(users).where(users.c.id == user_id)).mappings().first()
        if not u:
            raise HTTPException(404, 'Không tìm thấy tài khoản người dùng.')

        tier = u['tier']
        user_limit = u['posts_limit'] if u['posts_limit'] is not None else (10 if tier == 'free' else 999999)
        is_unlimited = (tier in ('pro', 'agency')) or (user_limit >= 999999)

        q = c.execute(
            select(usage_quotas).where(
                usage_quotas.c.user_id == user_id,
                usage_quotas.c.cycle == cycle
            )
        ).mappings().first()

        if not q:
            posts_used = 0
            quota_id = new_id()
            c.execute(usage_quotas.insert().values(
                id=quota_id,
                user_id=user_id,
                cycle=cycle,
                posts_used=0,
                posts_limit=user_limit,
                updated_at=now
            ))
        else:
            posts_used = q['posts_used']
            quota_id = q['id']

        # Enforce quota check
        if not is_unlimited and (posts_used + count > user_limit):
            remaining = max(0, user_limit - posts_used)
            raise HTTPException(
                status_code=429,
                detail=f'Bạn đã dùng hết {posts_used}/{user_limit} lượt đăng miễn phí trong tháng {cycle}. '
                       f'Vui lòng nâng cấp gói Pro để xuất bản không giới hạn.'
            )

        new_used = posts_used + count
        c.execute(
            update(usage_quotas)
            .where(usage_quotas.c.id == quota_id)
            .values(posts_used=new_used, posts_limit=user_limit, updated_at=now)
        )

    remaining = max(0, user_limit - new_used) if not is_unlimited else 999999
    return {
        'user_id': user_id,
        'cycle': cycle,
        'tier': tier,
        'posts_used': new_used,
        'posts_limit': user_limit,
        'remaining': remaining,
        'is_unlimited': is_unlimited
    }
