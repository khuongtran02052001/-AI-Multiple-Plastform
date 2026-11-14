import hashlib
import hmac
import secrets
import re
from cryptography.fernet import Fernet
import json


def _scrypt_derive(password_bytes: bytes, salt: bytes, n: int = 16384, r: int = 8, p: int = 1, length: int = 64) -> bytes:
    if hasattr(hashlib, 'scrypt'):
        return hashlib.scrypt(password_bytes, salt=salt, n=n, r=r, p=p)
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    kdf = Scrypt(salt=salt, length=length, n=n, r=r, p=p)
    return kdf.derive(password_bytes)


def password_hash(password):
    salt = secrets.token_bytes(16)
    value = _scrypt_derive(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f'scrypt${salt.hex()}${value.hex()}'


def verify_password(password, encoded):
    try:
        _, salt, value = encoded.split('$')
        actual = _scrypt_derive(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, length=len(bytes.fromhex(value)))
        return hmac.compare_digest(actual.hex(), value)
    except (ValueError, TypeError):
        return False


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Vault:
    def __init__(self, key):
        self.cipher = Fernet(key.encode())

    def encrypt(self, value):
        return self.cipher.encrypt(json.dumps(value).encode()).decode()

    def decrypt(self, value):
        return json.loads(self.cipher.decrypt(value.encode()))


def safe_error(message, secrets_to_hide=()):
    text = str(message)
    for value in secrets_to_hide:
        if value:
            text = text.replace(str(value), '[redacted]')
    text = re.sub(r'(?i)(access_token|refresh_token|client_secret|appsecret_proof)[=:"\s]+[^\s,&"}]+',
                  r'\1=[redacted]', text)
    text = re.sub(r'https?://\S+', '[URL redacted]', text)
    return text[:1000]
