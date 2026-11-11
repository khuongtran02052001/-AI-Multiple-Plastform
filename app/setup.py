"""Generate local secrets; never prints them. Run before starting the app."""
import getpass
import os
import re
import sys
import tempfile
from pathlib import Path
from cryptography.fernet import Fernet
from app.security import password_hash


def main():
    target = Path('.env')
    if target.exists():
        raise SystemExit('.env already exists. Edit it directly; setup will not overwrite secrets.')
    password = getpass.getpass('Admin password (at least 16 characters): ')
    if len(password) < 16 or password != getpass.getpass('Confirm password: '):
        raise SystemExit('Password too short or confirmation mismatch.')
    content = Path('.env.example').read_text()
    content = content.replace('ENCRYPTION_KEY=', f'ENCRYPTION_KEY={Fernet.generate_key().decode()}')
    # Compose interpolates unquoted $ in env files; single quotes keep the scrypt hash intact.
    content = content.replace('ADMIN_PASSWORD_HASH=', f"ADMIN_PASSWORD_HASH='{password_hash(password)}'")
    target.touch(mode=0o600)
    target.write_text(content)
    print('Created .env. Configure DATABASE_URL, BASE_URL and provider credentials before deployment.')


def rotate_admin():
    """Replace only the administrator password hash; preserve OAuth encryption keys."""
    target = Path('.env')
    if not target.is_file():
        raise SystemExit('.env is missing. Run setup before rotating the password.')
    old = target.read_text()
    matches = list(re.finditer('^ADMIN_PASSWORD_HASH=.*', old, flags=re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit('Expected exactly one ADMIN_PASSWORD_HASH line in .env.')
    password = getpass.getpass('New admin password (at least 16 characters): ')
    if len(password) < 16 or password != getpass.getpass('Confirm new password: '):
        raise SystemExit('Password too short or confirmation mismatch.')
    replacement = f"ADMIN_PASSWORD_HASH='{password_hash(password)}'"
    updated = old[:matches[0].start()] + replacement + old[matches[0].end():]
    # Atomic update, restrictive permissions, and no secrets in command-line arguments.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, prefix='.env-',
                                         delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print('Admin password hash rotated in .env. Recreate publisher and revoke existing sessions.')


if __name__ == '__main__':
    if len(sys.argv) == 1:
        main()
    elif sys.argv[1:] == ['rotate-admin']:
        rotate_admin()
    else:
        raise SystemExit('Usage: python -m app.setup [rotate-admin]')

