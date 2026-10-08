"""Encryption and display helpers for Apprise URLs.

An Apprise URL usually carries a credential (a token in the path, a password
in the user-info). It is stored encrypted with a key derived from the app
SECRET_KEY, and API responses only ever show ``url_hint``.
"""

from base64 import urlsafe_b64encode
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from config.settings import settings

_HKDF_INFO = b"nexus-novel notification channels v1"


def _fernet() -> Fernet:
    # Derived per call from the current SECRET_KEY; the key is cheap to derive
    # and this keeps the module free of import-time state.
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(
        settings.SECRET_KEY.encode()
    )
    return Fernet(urlsafe_b64encode(key))


def encrypt_url(url: str) -> str:
    return _fernet().encrypt(url.encode()).decode()


def decrypt_url(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def url_hint(url: str) -> str:
    """Show the scheme and host only: no path, query, user-info or password."""
    parts = urlsplit(url.strip())
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}/..." if host else f"{parts.scheme}://..."
