from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE)

    mongodb_uri: str
    mongodb_db_name: str = "climate_hazard"
    cors_allowed_origins: str = "http://localhost:5173"
    rate_limit_default: str = "60/minute"
    rate_limit_compute: str = "10/minute"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
