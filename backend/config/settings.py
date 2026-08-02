from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional


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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30, description="JWT token expiration in minutes"
    )
    METADATA_SERVER_URL: str = Field(
        default="http://127.0.0.1:8004",
        description="URL for the metadata scraping server",
    )
    METADATA_API_KEY: str = Field(default="", description="Internal Nexus Server API key")
    METADATA_ADMIN_API_KEY: str = Field(default="", description="Internal Nexus Server administrator key")

    def validate_required(self) -> list[str]:
        missing = []
        if not self.SECRET_KEY or self.SECRET_KEY == "supersecretkey":
            missing.append("SECRET_KEY")
        return missing


settings = Settings()

missing_vars = settings.validate_required()
if missing_vars:
    import sys

    print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}")
    print("Please set these in your .env file or environment.")
    sys.exit(1)
