import json
import os
import secrets
import tempfile
from base64 import urlsafe_b64encode
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# Values that have shipped as defaults in code, Compose files or docs. A token
# signed with any of them can be forged by anyone, so they are never used.
INSECURE_SECRET_KEYS = {
    "",
    "supersecretkey",
    "dev-secret-key-do-not-use-in-production",
    "development-only-secret",
    "nexus-local-development-secret-change-me",
    "replace-with-a-long-random-secret",
}


def _persisted_secret_key(download_path: str) -> str:
    """Return a random signing key that survives restarts.

    The key lives in the downloads volume, the only state the API and worker
    containers persist, so a fresh install is secure without manual setup.
    """
    path = Path(
        os.getenv("NEXUS_SECRET_KEY_FILE")
        or Path(download_path).expanduser() / ".nexus-secret-key"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as handle:
            handle.write(secrets.token_urlsafe(48))
    return path.read_text().strip()


def _b64url(raw: bytes) -> str:
    return urlsafe_b64encode(raw).rstrip(b"=").decode()


def _generate_vapid_keys() -> dict[str, str]:
    """Create a P-256 key pair in the raw form Web Push clients expect."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return {"private_key": _b64url(private_raw), "public_key": _b64url(public_raw)}


def _persisted_vapid_keys(download_path: str) -> dict[str, str]:
    """Return a VAPID key pair that survives restarts, creating it once.

    Stored beside the secret key in the downloads volume. The file is written
    to a temporary name and hard-linked into place, so the API and the worker
    starting together never read a half-written file. The first writer wins.
    """
    path = Path(
        os.getenv("NEXUS_VAPID_KEY_FILE")
        or Path(download_path).expanduser() / ".nexus-vapid.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".nexus-vapid-")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(_generate_vapid_keys(), handle)
            os.chmod(temp_name, 0o600)
            try:
                os.link(temp_name, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temp_name)
    keys = json.loads(path.read_text())
    return {"private_key": keys["private_key"], "public_key": keys["public_key"]}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    DATABASE_URL: str = Field(
        default="sqlite:///./test.db", description="Database connection URL"
    )
    DOWNLOAD_PATH: str = Field(
        default="./downloads", description="Path for downloaded novels"
    )
    BACKEND_PORT: int = Field(default=8000, description="Port for the backend server")
    SECRET_KEY: str = Field(
        default="dev-secret-key-do-not-use-in-production",
        description="Secret key for JWT token generation",
    )
    ALGORITHM: str = Field(default="HS256", description="Algorithm for JWT tokens")
    # Access tokens are short-lived; the browser renews them with the
    # HttpOnly refresh cookie, which rotates on every use.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=15, description="JWT access token expiration in minutes"
    )
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=30, description="Refresh token lifetime; each use starts a new period"
    )
    REFRESH_COOKIE_SECURE: str = Field(
        default="auto",
        description="Mark the refresh cookie Secure: auto (when the request came over HTTPS), true or false",
    )
    RUN_MIGRATIONS_ON_STARTUP: bool = Field(
        default=True, description="Run Alembic upgrade head when the API or worker starts"
    )
    METADATA_SERVER_URL: str = Field(
        default="http://127.0.0.1:8004",
        description="URL for the metadata scraping server",
    )
    METADATA_API_KEY: str = Field(default="", description="Internal Nexus Server API key")
    METADATA_ADMIN_API_KEY: str = Field(default="", description="Internal Nexus Server administrator key")
    NOTIFY_ALLOW_PRIVATE_HOSTS: bool = Field(
        default=False,
        description="Allow notification targets on private networks (e.g. a LAN ntfy server); any user could then reach them",
    )
    # Web Push identity. Leave the keys empty to use the pair persisted in
    # DOWNLOAD_PATH; set both to supply your own (the public key must match).
    VAPID_PRIVATE_KEY: str = Field(default="", description="VAPID private key (raw base64url); empty = persisted pair")
    VAPID_PUBLIC_KEY: str = Field(default="", description="VAPID public key (raw base64url); empty = persisted pair")
    VAPID_SUBJECT: str = Field(
        default="mailto:admin@localhost",
        description="Contact for push services, mailto: or https: URL",
    )

    # Single sign-on through an OpenID Connect provider (Authelia, Authentik,
    # Keycloak, ...). Enabled when issuer and client id are set.
    NEXUS_OIDC_ISSUER: str = Field(default="", description="OIDC issuer URL; empty disables single sign-on")
    NEXUS_OIDC_CLIENT_ID: str = Field(default="", description="OIDC client id")
    NEXUS_OIDC_CLIENT_SECRET: str = Field(default="", description="OIDC client secret")
    NEXUS_OIDC_SCOPES: str = Field(default="openid profile email", description="Scopes requested at sign-in")
    NEXUS_OIDC_DISPLAY_NAME: str = Field(default="SSO", description="Provider name on the sign-in button")
    NEXUS_OIDC_REDIRECT_URI: str = Field(
        default="",
        description="Callback URL registered at the provider; empty = derived from the request",
    )
    NEXUS_OIDC_USERNAME_CLAIM: str = Field(default="preferred_username", description="Claim used as the username")
    NEXUS_OIDC_ADMIN_GROUP: str = Field(default="", description="Group whose members are administrators")
    NEXUS_OIDC_GROUPS_CLAIM: str = Field(default="groups", description="Claim that lists the user's groups")
    NEXUS_OIDC_AUTO_CREATE: str = Field(
        default="",
        description="Create accounts on first sign-in: empty follows the sign-up mode, true always, false never",
    )
    NEXUS_PASSWORD_LOGIN: str = Field(default="enabled", description="Password sign-in: enabled or disabled")

    # Native Kobo sync (experimental, docs/kobo-sync.md).
    NEXUS_KOBO_STORE_PROXY: bool = Field(
        default=False,
        description="Forward Kobo requests Nexus does not handle to the Kobo store (keeps store purchases working)",
    )
    NEXUS_KOBO_BASE_URL: str = Field(
        default="",
        description="External API URL the Kobo reaches, e.g. http://192.168.1.5:8180/api; empty = derived from requests",
    )
    NEXUS_KEPUBIFY_PATH: str = Field(default="", description="kepubify binary; empty = look it up on PATH")

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.NEXUS_OIDC_ISSUER.strip() and self.NEXUS_OIDC_CLIENT_ID.strip())

    @property
    def password_login_enabled(self) -> bool:
        # Never lock everyone out: without single sign-on, passwords stay on.
        return self.NEXUS_PASSWORD_LOGIN.strip().lower() != "disabled" or not self.oidc_enabled

    def model_post_init(self, __context) -> None:
        if self.SECRET_KEY.strip() in INSECURE_SECRET_KEYS:
            self.SECRET_KEY = _persisted_secret_key(self.DOWNLOAD_PATH)
        if not (self.VAPID_PRIVATE_KEY.strip() and self.VAPID_PUBLIC_KEY.strip()):
            keys = _persisted_vapid_keys(self.DOWNLOAD_PATH)
            self.VAPID_PRIVATE_KEY = keys["private_key"]
            self.VAPID_PUBLIC_KEY = keys["public_key"]


settings = Settings()
