from test_publisher import setup, login, account, payload
from sqlalchemy import update
from app.db import posts


def test_task_projection_cancel_and_terminal_guard(setup):
    settings, engine, _, client = setup
    headers=login(client); account(engine,settings)
    result=client.post('/api/posts',headers=headers,json=payload(action='draft'))
    assert result.status_code==200
    task=client.get('/api/tasks').json()['tasks'][0]
    assert task['status']=='draft' and task['can_cancel']
    assert 'tokens' not in task
    assert client.post(f"/api/tasks/post/{task['id']}/cancel",headers=headers).status_code==200
    assert client.post(f"/api/tasks/post/{task['id']}/cancel",headers=headers).status_code==409
    with engine.begin() as c: c.execute(update(posts).values(status='unknown'))
    task=client.get('/api/tasks').json()['tasks'][0]
    assert not task['can_retry'] and not task['can_cancel']
    assert client.get('/api/tasks?limit=101').status_code==400


def test_task_endpoints_require_login(setup):
    _,_,_,client=setup
    assert client.get('/api/tasks').status_code==401
    assert client.post('/api/tasks/post/missing/cancel').status_code in (401,403)
