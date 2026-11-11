from pathlib import Path

from app.security import verify_password
from app.setup import main, rotate_admin


def test_setup_and_rotation_preserve_encryption_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path('.env.example').write_text('ENCRYPTION_KEY=\nADMIN_PASSWORD_HASH=\nDATABASE_URL=sqlite:///local.db\n')
    passwords = iter(['long-original-password', 'long-original-password',
                      'replacement-password-123', 'replacement-password-123'])
    monkeypatch.setattr('app.setup.getpass.getpass', lambda _: next(passwords))
    main()
    first = Path('.env').read_text()
    assert "ADMIN_PASSWORD_HASH='scrypt$" in first
    first_hash = next(x for x in first.splitlines() if x.startswith('ADMIN_PASSWORD_HASH=')).split('=', 1)[1].strip("'")
    assert verify_password('long-original-password', first_hash)
    key = next(x for x in first.splitlines() if x.startswith('ENCRYPTION_KEY='))
    assert Path('.env').stat().st_mode & 0o777 == 0o600

    rotate_admin()
    second = Path('.env').read_text()
    second_hash = next(x for x in second.splitlines() if x.startswith('ADMIN_PASSWORD_HASH=')).split('=', 1)[1].strip("'")
    assert verify_password('replacement-password-123', second_hash)
    assert not verify_password('long-original-password', second_hash)
    assert key in second
    assert 'DATABASE_URL=sqlite:///local.db' in second
    assert Path('.env').stat().st_mode & 0o777 == 0o600
