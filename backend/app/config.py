from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # hide_input_in_errors: un errore di validazione (es. token troppo corto) non deve
    # stampare nei log del container il valore del token o della password AnkiWeb
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    anki_api_token: str = Field(min_length=16)
    # In alternativa al token in chiaro nell'ambiente: il percorso di un file che lo contiene
    # (Docker secret, es. /run/secrets/anki_api_token). Vince il file, se c'è.
    anki_api_token_file: Path | None = None
    anki_data_dir: Path = Path("./data")
    anki_cors_origins: str = ""
    anki_auto_sync_minutes: float = 10
    anki_sync_on_startup: bool = True

    # Server di sync: vuoto = AnkiWeb. Per un server self-hosted (anche quello
    # incluso nel pacchetto `anki`, python -m anki.syncserver) es. http://host:8080/
    anki_sync_endpoint: str | None = None
    # timeout di rete delle sync (secondi senza dati prima di arrendersi)
    anki_sync_io_timeout: int = 60
    # quanto una richiesta aspetta la collezione occupata (es. sync) prima del 503
    anki_busy_timeout: float = 20

    # tentativi sbagliati prima del blocco (per IP) e durata della finestra
    anki_token_max_failures: int = 20
    anki_token_window_s: float = 600
    anki_login_max_failures: int = 5
    anki_login_window_s: float = 900

    # lingua di Anki per intervalli dei pulsanti ("4g"), riepiloghi e messaggi di sync
    anki_lang: str = "it"

    anki_log_format: Literal["text", "json"] = "text"
    anki_log_level: str = "INFO"

    ankiweb_username: str | None = None
    ankiweb_password: str | None = None

    # Build della PWA da servire sulla stessa origine (app/web.py). Vuoto = solo API
    # (sviluppo: la PWA la serve Vite). Nell'immagine Docker vale /srv/web.
    anki_web_dir: Path | None = None
    # Versione e commit dell'immagine (build arg, vedi Dockerfile): li mostra /api/health.
    anki_studio_version: str = "dev"
    anki_studio_revision: str = ""

    @field_validator("anki_web_dir", "anki_api_token_file", mode="before")
    @classmethod
    def _empty_is_none(cls, v):
        return None if v == "" else v

    @model_validator(mode="before")
    @classmethod
    def _token_from_file(cls, data):
        if not isinstance(data, dict):
            return data
        path = data.get("anki_api_token_file") or data.get("ANKI_API_TOKEN_FILE")
        if not path:
            return data
        try:
            token = Path(path).read_text(encoding="utf-8").strip()
        except OSError as e:
            # niente contenuto del file nel messaggio: solo il percorso e l'errore
            raise ValueError(f"ANKI_API_TOKEN_FILE: impossibile leggere {path} ({e.strerror})") from None
        return {**data, "anki_api_token": token}

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
    def backup_dir(self) -> Path:
        return self.anki_data_dir / "backups"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.anki_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
