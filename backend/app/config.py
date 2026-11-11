from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # hide_input_in_errors: un errore di validazione (es. token troppo corto) non deve
    # stampare nei log del container il valore del token o della password AnkiWeb
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    # ---- accesso -------------------------------------------------------------
    # La PWA entra con il login OIDC (Authentik): il backend è un client confidenziale,
    # fa lo scambio del codice e tiene la sessione in un cookie HttpOnly (app/oidc.py).
    # Nel browser non resta nessun token.
    #
    # URL pubblico dell'app, es. https://anki.jshep.xyz: da qui la redirect URI
    # (<url>/api/auth/callback) e l'origine attesa per le richieste che modificano dati.
    # Esplicito e non preso dall'header Host, che arriva dal client.
    anki_public_url: str | None = None
    # Issuer del provider, es. https://auth.jshep.xyz/application/o/anki-studio/
    anki_oidc_issuer: str | None = None
    anki_oidc_client_id: str | None = None
    anki_oidc_client_secret: str | None = None
    # Docker secret con il client secret (es. /run/secrets/anki_oidc_client_secret). Vince il file.
    anki_oidc_client_secret_file: Path | None = None
    anki_oidc_scopes: str = "openid profile email"
    # Seconda barriera dopo le policy dell'applicazione su Authentik (separati da virgola):
    # vuoti = basta che Authentik autorizzi l'utente. Utenti: preferred_username o email.
    anki_oidc_allowed_users: str = ""
    anki_oidc_allowed_groups: str = ""
    # Durata della sessione della PWA. Scaduta, la PWA rifà da sola il login su Authentik
    # (se la sessione di Authentik è ancora valida, senza chiedere niente).
    anki_session_days: float = 30

    # ---- server MCP (/mcp, docs/PIANO-HUB.md) --------------------------------------
    # Spento = niente /mcp né .well-known. Gli accessi sono due: i token `ask_…` (e il vecchio
    # ANKI_API_TOKEN) e, per l'app Claude, OAuth con un SECONDO provider Authentik. Il backend
    # non è il client OAuth di quel provider (lo è Claude): riceve solo i JWT e ne verifica la
    # firma con il JWKS, quindi non ha un client secret.
    anki_mcp_enabled: bool = True
    # Issuer del provider/applicazione per Claude, es.
    # https://auth.jshep.xyz/application/o/anki-studio-mcp/ (solo https). Vuoto = niente OAuth.
    anki_mcp_oidc_issuer: str | None = None
    # Client ID del provider: è il valore atteso nell'`aud` dei JWT (non l'URL della risorsa)
    anki_mcp_oidc_client_id: str | None = None

    # Solo sviluppo, senza Authentik: /api/auth/login apre subito una sessione "dev".
    # Rifiutato se il processo serve anche la PWA (ANKI_WEB_DIR, cioè l'immagine Docker).
    anki_dev_login: bool = False

    # Facoltativo, per script e test (curl, smoke test): `Authorization: Bearer <token>`.
    # La PWA non lo usa più; nello stack non va impostato.
    anki_api_token: str | None = Field(default=None, min_length=16)
    # In alternativa al token in chiaro nell'ambiente: il percorso di un file che lo contiene
    # (Docker secret, es. /run/secrets/anki_api_token). Vince il file, se c'è.
    anki_api_token_file: Path | None = None
    anki_data_dir: Path = Path("./data")
    anki_cors_origins: str = ""
    anki_auto_sync_minutes: float = 10
    anki_sync_on_startup: bool = True
    # Dopo una scrittura da agente (o dalle rotte hub) la sync parte da sola dopo questi
    # secondi, con più scritture raggruppate in una sola sync. 0 = spenta.
    anki_sync_after_write_seconds: float = Field(default=30, ge=0)

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

    @field_validator(
        "anki_web_dir",
        "anki_api_token_file",
        "anki_api_token",
        "anki_oidc_client_secret_file",
        "anki_oidc_client_secret",
        "anki_oidc_issuer",
        "anki_oidc_client_id",
        "anki_public_url",
        "anki_mcp_oidc_issuer",
        "anki_mcp_oidc_client_id",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, v):
        return None if v == "" else v

    @model_validator(mode="before")
    @classmethod
    def _secrets_from_files(cls, data):
        if not isinstance(data, dict):
            return data
        for field in ("anki_api_token", "anki_oidc_client_secret"):
            env = f"{field}_file".upper()
            path = data.get(f"{field}_file") or data.get(env)
            if not path:
                continue
            try:
                value = Path(path).read_text(encoding="utf-8").strip()
            except OSError as e:
                # niente contenuto del file nel messaggio: solo il percorso e l'errore
                raise ValueError(f"{env}: impossibile leggere {path} ({e.strerror})") from None
            data = {**data, field: value}
        return data

    @field_validator("anki_api_token")
    @classmethod
    def _not_placeholder(cls, v: str | None) -> str | None:
        if v == "cambia-questo-token":
            raise ValueError("imposta un ANKI_API_TOKEN vero o toglilo (vedi .env.example)")
        return v

    @field_validator("anki_public_url", "anki_oidc_issuer")
    @classmethod
    def _http_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("https://", "http://")):
            raise ValueError("deve essere un URL http(s)://")
        return v

    @field_validator("anki_mcp_oidc_issuer")
    @classmethod
    def _https_issuer(cls, v: str | None) -> str | None:
        # i JWT valgono quanto il canale da cui arrivano le chiavi di verifica: solo TLS,
        # senza eccezioni (nemmeno localhost: i test non fanno rete, usano un JWKS finto)
        if v is not None and not v.startswith("https://"):
            raise ValueError("ANKI_MCP_OIDC_ISSUER deve essere https://")
        return v

    @model_validator(mode="after")
    def _mcp_oauth_complete(self):
        mcp = (self.anki_mcp_oidc_issuer, self.anki_mcp_oidc_client_id)
        if any(mcp) and not (all(mcp) and self.anki_public_url):
            raise ValueError(
                "OAuth di /mcp incompleto: servono ANKI_PUBLIC_URL, ANKI_MCP_OIDC_ISSUER "
                "e ANKI_MCP_OIDC_CLIENT_ID"
            )
        return self

    @model_validator(mode="after")
    def _oidc_complete(self):
        oidc = (self.anki_oidc_issuer, self.anki_oidc_client_id, self.anki_oidc_client_secret)
        if any(oidc) and not (all(oidc) and self.anki_public_url):
            raise ValueError(
                "OIDC incompleto: servono ANKI_PUBLIC_URL, ANKI_OIDC_ISSUER, "
                "ANKI_OIDC_CLIENT_ID e ANKI_OIDC_CLIENT_SECRET(_FILE)"
            )
        return self

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.anki_oidc_issuer)

    @property
    def mcp_oauth_enabled(self) -> bool:
        return self.anki_mcp_enabled and bool(self.anki_mcp_oidc_issuer)

    @property
    def mcp_resource_url(self) -> str | None:
        """L'URL che l'utente inserisce in Claude, senza slash finale: è la `resource` dei metadati."""
        return self.anki_public_url.rstrip("/") + "/mcp" if self.anki_public_url else None

    @property
    def public_origin(self) -> str | None:
        """Schema, host e porta di ANKI_PUBLIC_URL (come l'header Origin del browser)."""
        if not self.anki_public_url:
            return None
        parts = urlsplit(self.anki_public_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def redirect_uri(self) -> str:
        assert self.anki_public_url
        return self.anki_public_url.rstrip("/") + "/api/auth/callback"

    @property
    def allowed_users(self) -> set[str]:
        return {u.strip().lower() for u in self.anki_oidc_allowed_users.split(",") if u.strip()}

    @property
    def allowed_groups(self) -> set[str]:
        return {g.strip() for g in self.anki_oidc_allowed_groups.split(",") if g.strip()}

    @property
    def collection_path(self) -> Path:
        return self.anki_data_dir / "collection.anki2"

    @property
    def sync_auth_path(self) -> Path:
        return self.anki_data_dir / "sync_auth.json"

    @property
    def tokens_path(self) -> Path:
        return self.anki_data_dir / "tokens.json"

    @property
    def journal_path(self) -> Path:
        """Il diario delle operazioni degli agenti (app/journal.py)."""
        return self.anki_data_dir / "agent-ops.json"

    @property
    def backup_dir(self) -> Path:
        return self.anki_data_dir / "backups"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.anki_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
