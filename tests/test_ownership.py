from test_publisher import setup, login, account, payload
from sqlalchemy import update, select
from app.db import sessions, users


def test_user_cannot_publish_to_another_owners_account(setup):
    settings, engine, _, client = setup
    headers = login(client)
    account(engine, settings)
    with engine.begin() as c:
        owner = dict(c.execute(select(users)).mappings().first())
        owner.update(id='unprivileged-user', email='other@example.test')
        c.execute(users.insert().values(**owner))
        c.execute(update(sessions).values(user_id='unprivileged-user'))
    # Draft avoids quota mutation and must still enforce destination ownership.
    result = client.post('/api/posts', headers=headers, json=payload(action='draft'))
    assert result.status_code == 403


def test_disabled_user_session_is_rejected(setup):
    settings, engine, _, client = setup
    login(client)
    with engine.begin() as c:
        c.execute(update(users).values(status='disabled'))
    assert client.get('/api/accounts').status_code == 401


def test_quota_rolls_back_with_parent_transaction(setup):
    from app.quota import validate_and_consume_quota
    from app.db import usage_quotas
    settings, engine, _, client = setup
    login(client)
    with engine.connect() as c:
        user_id = c.execute(select(users.c.id)).scalar_one()
    try:
        with engine.begin() as c:
            validate_and_consume_quota(engine, user_id, connection=c)
            raise RuntimeError('simulate post insert failure')
    except RuntimeError:
        pass
    with engine.connect() as c:
        assert c.execute(select(usage_quotas)).first() is None
