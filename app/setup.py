"""Generate local secrets; never prints them. Run before starting the app."""
import getpass
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


if __name__ == '__main__':
    main()
