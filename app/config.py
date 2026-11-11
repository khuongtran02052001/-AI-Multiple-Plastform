import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class Settings:
    database_url: str = os.getenv('DATABASE_URL', 'sqlite:///./data/local.db')
    base_url: str = os.getenv('BASE_URL', 'http://localhost:8000').rstrip('/')
    data_dir: Path = Path(os.getenv('DATA_DIR', './data'))
    encryption_key: str = os.getenv('ENCRYPTION_KEY', '')
    admin_password_hash: str = os.getenv('ADMIN_PASSWORD_HASH', '')
    google_client_id: str = os.getenv('GOOGLE_CLIENT_ID', '')
    google_client_secret: str = os.getenv('GOOGLE_CLIENT_SECRET', '')
    meta_app_id: str = os.getenv('META_APP_ID', '')
    meta_app_secret: str = os.getenv('META_APP_SECRET', '')
    meta_api_version: str = os.getenv('META_API_VERSION', 'v23.0')
    max_upload_mb: int = int(os.getenv('MAX_UPLOAD_MB', '250'))
    max_storage_mb: int = int(os.getenv('MAX_STORAGE_MB', '5000'))
    retention_days: int = int(os.getenv('MEDIA_RETENTION_DAYS', '7'))
    worker_enabled: bool = os.getenv('WORKER_ENABLED', 'true').lower() == 'true'

    @property
    def secure(self):
        return self.base_url.startswith('https://')

    def validate(self):
        from cryptography.fernet import Fernet
        Fernet(self.encryption_key.encode())
        if not self.admin_password_hash.startswith('scrypt$'):
            raise ValueError('Run python -m app.setup first; ADMIN_PASSWORD_HASH is missing.')
        p = urlparse(self.base_url)
        if p.scheme not in ('http', 'https') or not p.hostname or p.path not in ('', '/'):
            raise ValueError('BASE_URL must be an origin without a path.')
        if not self.secure and p.hostname not in ('localhost', '127.0.0.1'):
            raise ValueError('HTTPS is required outside localhost.')
        if self.database_url.startswith('postgres://'):
            self.database_url = self.database_url.replace('postgres://', 'postgresql+psycopg://', 1)
        elif self.database_url.startswith('postgresql://'):
            self.database_url = self.database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
        if self.database_url.startswith('postgresql'):
            from sqlalchemy.engine import make_url
            db = make_url(self.database_url)
            if db.host not in ('localhost', '127.0.0.1', '::1') and db.query.get('sslmode') not in ('require', 'verify-ca', 'verify-full'):
                raise ValueError('Remote PostgreSQL requires sslmode=require or verify-full.')
        if not 1 <= self.max_upload_mb <= 2048 or self.max_storage_mb < self.max_upload_mb or self.retention_days < 1:
            raise ValueError('Invalid upload, storage or retention limit.')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / 'media').mkdir(exist_ok=True)


settings = Settings()
