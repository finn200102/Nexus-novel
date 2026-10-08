import os
import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional

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
    # Long enough that readers are not signed out mid-session; there is no
    # refresh token yet, so an expired token always means a new login.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60 * 24 * 30, description="JWT token expiration in minutes"
    )
    METADATA_SERVER_URL: str = Field(
        default="http://127.0.0.1:8004",
        description="URL for the metadata scraping server",
    )
    METADATA_API_KEY: str = Field(default="", description="Internal Nexus Server API key")
    METADATA_ADMIN_API_KEY: str = Field(default="", description="Internal Nexus Server administrator key")

    def model_post_init(self, __context) -> None:
        if self.SECRET_KEY.strip() in INSECURE_SECRET_KEYS:
            self.SECRET_KEY = _persisted_secret_key(self.DOWNLOAD_PATH)


settings = Settings()
