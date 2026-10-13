from functools import lru_cache
from pathlib import Path
from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_RATE_LIMIT_DEFAULTS = {
    "rate_limit_default": "120/minute",
    "rate_limit_compute": "30/minute",
}

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE)
    mongodb_uri: str
    mongodb_db_name: str = "climate_hazard"
    cors_allowed_origins: str = "http://localhost:5173"
    rate_limit_default: str = _RATE_LIMIT_DEFAULTS["rate_limit_default"]
    rate_limit_compute: str = _RATE_LIMIT_DEFAULTS["rate_limit_compute"]
    trusted_proxy_hops: int = 0

    @field_validator(*_RATE_LIMIT_DEFAULTS)
    @classmethod
    def _fallback_to_default(cls, value: str, info: ValidationInfo) -> str:
        return value.strip() or _RATE_LIMIT_DEFAULTS[info.field_name]

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
