"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings; all values have local-development defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./app.db"
    upload_dir: Path = Path("./uploads")

    # Upload limits (see geo/validation.py for enforcement points).
    max_upload_mb: int = 50
    max_uncompressed_mb: int = 200
    max_files_in_zip: int = 50
    max_features: int = 20_000

    # Pagination bounds.
    default_page_size: int = 50
    max_page_size: int = 200


settings = Settings()
