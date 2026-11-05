from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anki_api_token: str = Field(min_length=16)
    anki_data_dir: Path = Path("./data")
    anki_cors_origins: str = ""
    anki_auto_sync_minutes: int = 10
    anki_sync_on_startup: bool = True

    ankiweb_username: str | None = None
    ankiweb_password: str | None = None

    @field_validator("anki_api_token")
    @classmethod
    def _not_placeholder(cls, v: str) -> str:
        if v == "cambia-questo-token":
            raise ValueError("imposta un ANKI_API_TOKEN vero (vedi .env.example)")
        return v

    @property
    def collection_path(self) -> Path:
        return self.anki_data_dir / "collection.anki2"

    @property
    def sync_auth_path(self) -> Path:
        return self.anki_data_dir / "sync_auth.json"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.anki_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
