from test_publisher import setup, login, account, payload
from sqlalchemy import update
from app.db import sessions


def test_user_cannot_publish_to_another_owners_account(setup):
    settings, engine, _, client = setup
    headers = login(client)
    account(engine, settings)
    with engine.begin() as c:
        c.execute(update(sessions).values(user_id='unprivileged-user'))
    # Draft avoids quota mutation and must still enforce destination ownership.
    result = client.post('/api/posts', headers=headers, json=payload(action='draft'))
    assert result.status_code == 403
