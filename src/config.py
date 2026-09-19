from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/foodanalyzer"

    max_image_size_mb: float = 5.0
    allowed_content_types: tuple[str, ...] = ("image/jpeg", "image/png")

    nutrition_cache_ttl_seconds: int = 86400
    nutrition_concurrency_limit: int = 10

    max_retries: int = 3
    retry_backoff_seconds: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
