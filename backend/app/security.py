"""Sessioni della PWA, limiti ai tentativi e header di sicurezza."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import re
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request, status
from starlette.requests import HTTPConnection

from .config import Settings, get_settings
from .journal import ADMIN_ACTOR, SESSION_ACTOR, Actor
from .logging_setup import register_secret
from .tokens import TOKEN_PREFIX, TokenStore, agent_slug

log = logging.getLogger(__name__)

SESSION_COOKIE = "anki_studio_session"
# stato del login in corso (state, nonce, PKCE): vive pochi minuti, solo su /api/auth
LOGIN_COOKIE = "anki_studio_login"


class RateLimiter:
    """Finestra scorrevole in memoria, per chiave (di solito l'IP del client).

    Basta un solo processo (è il nostro caso): niente Redis.
    """

    def __init__(self, max_events: int, window_s: float) -> None:
        self.max_events = max_events
        self.window_s = window_s
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._events.setdefault(key, deque())
        while q and q[0] <= now - self.window_s:
            q.popleft()
        return q

    def retry_after(self, key: str) -> int:
        """0 se si può procedere, altrimenti i secondi da aspettare."""
        if self.max_events <= 0:
            return 0
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) < self.max_events:
                return 0
            return max(1, math.ceil(q[0] + self.window_s - now))

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now).append(now)
            # non lasciamo crescere la mappa all'infinito con IP casuali
            if len(self._events) > 10_000:
                for k in [k for k, v in self._events.items() if not v][:5_000]:
                    del self._events[k]

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


def client_key(request: HTTPConnection) -> str:
    # dietro Traefik l'IP vero arriva da X-Forwarded-For, che uvicorn
    # applica solo se il proxy è fidato (FORWARDED_ALLOW_IPS, vedi Dockerfile)
    return request.client.host if request.client else "unknown"


def _too_many(retry: int, what: str) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        f"Troppi tentativi {what}: riprova tra {retry} s",
        headers={"Retry-After": str(retry)},
    )


class Signer:
    """Cookie firmati (HMAC-SHA256) con scadenza: `base64(json).base64(firma)`.

    Lo scopo entra nella firma, così un cookie del login non vale come sessione.
    Il contenuto è leggibile da chi ha il cookie: niente segreti dentro, solo chi è
    l'utente e quando scade.
    """

    def __init__(self, key: bytes) -> None:
        self._key = key

    def _mac(self, purpose: str, body: str) -> str:
        mac = hmac.new(self._key, f"{purpose}.{body}".encode(), hashlib.sha256).digest()
        return _b64(mac)

    def dumps(self, purpose: str, payload: dict, max_age_s: float) -> str:
        data = {**payload, "exp": int(time.time() + max_age_s)}
        body = _b64(json.dumps(data, separators=(",", ":")).encode())
        return f"{body}.{self._mac(purpose, body)}"

    def loads(self, purpose: str, value: str | None) -> dict | None:
        if not value or value.count(".") != 1:
            return None
        body, mac = value.split(".")
        if not secrets.compare_digest(mac, self._mac(purpose, body)):
            return None
        try:
            data = json.loads(_unb64(body))
        except ValueError:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("exp"), int):
            return None
        return data if data["exp"] > time.time() else None


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def session_key(settings: Settings) -> bytes:
    """Chiave dei cookie: derivata dal client secret OIDC, così sopravvive ai riavvii
    (aggiornamenti dell'immagine) senza un altro segreto da gestire. Cambiare il client
    secret su Authentik chiude tutte le sessioni, che è quello che si vuole."""
    if settings.anki_oidc_client_secret:
        return hmac.new(
            settings.anki_oidc_client_secret.encode(), b"anki-studio-session-v1", hashlib.sha256
        ).digest()
    # solo sviluppo (ANKI_DEV_LOGIN): sessioni valide finché gira il processo
    return secrets.token_bytes(32)


def cookie_secure(request: Request) -> bool:
    # su http://localhost (sviluppo) Safari scarterebbe un cookie Secure;
    # dietro Traefik lo schema arriva come https grazie a --proxy-headers
    return not (
        request.url.scheme == "http" and request.url.hostname in ("localhost", "127.0.0.1")
    )


def read_session(request: HTTPConnection) -> dict | None:
    signer: Signer = request.app.state.signer
    return signer.loads("session", request.cookies.get(SESSION_COOKIE))


def _bearer(request: HTTPConnection) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def check_blocked(request: HTTPConnection) -> None:
    """Limite ai fallimenti del login OIDC (callback con state sbagliato): `token_limiter`.
    Non riguarda i Bearer, che hanno il loro (`check_bearer_blocked`)."""
    limiter: RateLimiter = request.app.state.token_limiter
    retry = limiter.retry_after(client_key(request))
    if retry:
        raise _too_many(retry, "con credenziali sbagliate")


def record_auth_failure(request: HTTPConnection, what: str) -> None:
    key = client_key(request)
    request.app.state.token_limiter.hit(key)
    log.warning("%s non valido", what, extra={"client": key, "path": request.url.path})


def check_bearer_blocked(request: HTTPConnection) -> None:
    """Blocco per troppi Bearer sbagliati, SOLO per le richieste che presentano un Bearer.

    Il limite difende dall'indovinare un token, quindi vale per chi prova un token: bloccato
    anche con la credenziale giusta (altrimenti chi indovina se ne accorgerebbe). Chi non manda
    un Bearer, cioè la PWA con il cookie di sessione, non indovina niente e non si ferma: un
    agente che ritenta in loop da un IP non deve chiudere fuori il proprietario."""
    if _bearer(request) is None:
        return
    retry = request.app.state.bearer_limiter.retry_after(client_key(request))
    if retry:
        raise _too_many(retry, "con credenziali sbagliate")


def record_bearer_failure(request: HTTPConnection, what: str) -> None:
    key = client_key(request)
    request.app.state.bearer_limiter.hit(key)
    log.warning("%s non valido", what, extra={"client": key, "path": request.url.path})


def is_revoked_bearer(request: HTTPConnection, token: str) -> bool:
    """Un token `ask_…` che esisteva ed è stato revocato: risponde 401 ma NON conta come un
    tentativo di indovinare (è un agente configurato col token vecchio che ritenta)."""
    if not token.startswith(TOKEN_PREFIX):
        return False
    store: TokenStore = request.app.state.tokens
    return store.is_revoked(token)


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Accesso richiesto")


def _same_origin(request: HTTPConnection, settings: Settings) -> bool:
    """Contro il CSRF sulle richieste che modificano dati con il cookie di sessione.

    SameSite=Lax ferma gli altri siti, non gli altri sottodomini di jshep.xyz (stesso
    "sito"): per quelli serve guardare da dove parte la richiesta. Un browser manda
    sempre Sec-Fetch-Site (Safari dalla 16.4) o almeno Origin; un client senza nessuno
    dei due non è un browser, e quindi non può essere usato per un CSRF.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site == "same-origin"
    origin = request.headers.get("origin")
    if origin is None:
        return True
    # un WebSocket arriva come ws/wss, ma il browser manda l'Origin della pagina (http/https)
    scheme = {"ws": "http", "wss": "https"}.get(request.url.scheme, request.url.scheme)
    expected = settings.public_origin or f"{scheme}://{request.url.netloc}"
    return origin == expected


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class Identity:
    """Chi sta chiamando. `session` e `admin` (il vecchio ANKI_API_TOKEN) possono tutto;
    `token` (`ask_…`) è limitato da `scope` e dalla matrice qui sotto. `oauth` è l'app Claude
    che entra su /mcp con un JWT di Authentik (app/mcp_auth.py): vale come un token `write`
    e non esiste sulle rotte REST."""

    kind: Literal["session", "admin", "token", "oauth"]
    name: str
    # admin = nessun limite (sessione e ANKI_API_TOKEN); read/write = token con scope
    scope: Literal["admin", "read", "write"] = "admin"
    username: str | None = None
    token_id: str | None = None

    @property
    def scoped(self) -> bool:
        """Limitata da scope e matrice dei permessi (token `ask_…` e OAuth di /mcp)."""
        return self.kind in ("token", "oauth")

    @property
    def actor(self) -> Actor:
        """Come compare nel diario delle operazioni: lo slug del token, oppure «sessione» /
        «admin». Chi ha uno scope vede e annulla solo le proprie operazioni (`Actor.scoped`)."""
        if self.scoped:
            return Actor(self.agent or "", scoped=True)
        return Actor(ADMIN_ACTOR if self.kind == "admin" else SESSION_ACTOR)

    @property
    def agent(self) -> str | None:
        """Slug del tag di provenienza `agent::<slug>`: solo chi ha uno scope ne ha uno."""
        return agent_slug(self.name) if self.scoped else None


# ---- permessi dei token con scope --------------------------------------------------------
#
# Un solo posto, deny-by-default: una rotta nuova è vietata ai token finché non la si
# elenca qui. Sessione e ANKI_API_TOKEN non passano da qui. I percorsi sono quelli dopo
# il prefisso /api. `PATCH /notes/{id}` è ammessa per i token write, ma solo sulle note col
# proprio tag `agent::<nome>`: lo verifica la rotta (serve la collezione).

_READ_ROUTES = (
    "/decks",
    "/notetypes",
    "/search/notes",
    "/tags",
    r"/notes/\d+",
    r"/cards/\d+/preview",
    "/hub/operations",  # solo le proprie: lo decide la rotta
    "/sync",
)
_WRITE_ROUTES = (
    ("POST", "/hub/notes/batch"),
    ("POST", "/hub/decks"),
    ("POST", "/sync"),
    ("POST", "/media"),
    ("POST", r"/hub/operations/[^/]+/undo"),  # solo le proprie: lo decide la rotta
    ("PATCH", r"/notes/\d+"),  # solo note proprie, vedi sopra
)
_READ_RE = re.compile("|".join(f"(?:{p})" for p in _READ_ROUTES))
_WRITE_RE = [(m, re.compile(p)) for m, p in _WRITE_ROUTES]


def token_may(identity: Identity, method: str, path: str) -> bool:
    """La matrice "chi può cosa" per un token con scope (docs/PIANO-HUB.md). La usano anche gli
    strumenti MCP, con il percorso REST equivalente: un permesso solo, in un posto solo."""
    if not identity.scoped:
        return True
    api_path = path.removeprefix("/api")
    if method == "GET":
        return _READ_RE.fullmatch(api_path) is not None
    if identity.scope != "write":
        return False
    return any(method == m and rx.fullmatch(api_path) for m, rx in _WRITE_RE)


def _forbidden_for_token() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "Questo token non può fare questa operazione")


def match_bearer(request: HTTPConnection, token: str, settings: Settings) -> Identity | None:
    """L'identità di un token statico (`ANKI_API_TOKEN` o `ask_…`), o None. Non tocca il rate
    limit: chi chiama decide se un None è un tentativo sbagliato (vedi `_identify_bearer` e
    app/mcp_auth.py, che prima di arrendersi prova anche i JWT)."""
    expected = settings.anki_api_token
    if expected is not None and secrets.compare_digest(token.encode(), expected.encode()):
        return Identity(kind="admin", name="Token dell'API")
    if token.startswith(TOKEN_PREFIX):
        store: TokenStore = request.app.state.tokens
        stored = store.verify(token)
        if stored is not None:
            # il chiaro non è più in memoria dopo un riavvio: lo si registra qui, così
            # non compare nei log nemmeno se finisse in un messaggio d'errore
            register_secret(token)
            return Identity(
                kind="token",
                name=stored.name,
                scope=stored.scope,
                token_id=stored.id,
            )
    return None


def _identify_bearer(request: HTTPConnection, token: str, settings: Settings) -> Identity | None:
    """L'identità di un token Bearer, o None se non vale (e allora conta come tentativo
    sbagliato per il rate limit, tranne il caso descritto sotto)."""
    identity = match_bearer(request, token, settings)
    if identity is not None:
        return identity
    if is_revoked_bearer(request, token):
        return None
    if not token.startswith(TOKEN_PREFIX) and settings.anki_api_token is None:
        # nessun ANKI_API_TOKEN da indovinare: è la PWA di prima (in cache) con il token
        # vecchio, che non deve far bloccare l'IP proprio mentre passa al login con Authentik
        return None
    record_bearer_failure(request, "Token")
    return None


def require_auth(request: Request, settings: Settings = Depends(get_settings)) -> Identity:
    """Sessione OIDC (cookie HttpOnly) o, per script e agenti, `Authorization: Bearer`.

    Vale anche per i media: <img> e <audio> delle carte mandano il cookie da sé.
    Qui si applica anche, in un solo punto, la matrice dei permessi dei token con scope.
    """
    check_bearer_blocked(request)
    token = _bearer(request)
    if token is not None:
        identity = _identify_bearer(request, token, settings)
        if identity is None:
            raise _unauthorized()
        if not token_may(identity, request.method, request.url.path):
            log.warning(
                "Operazione non permessa al token",
                extra={"agent": identity.agent, "method": request.method, "path": request.url.path},
            )
            raise _forbidden_for_token()
        request.state.identity = identity
        return identity
    session = read_session(request)
    if session is None:
        raise _unauthorized()
    if request.method not in _SAFE_METHODS and not _same_origin(request, settings):
        log.warning(
            "Richiesta da un'altra origine rifiutata",
            extra={"client": client_key(request), "path": request.url.path},
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Richiesta da un'altra origine")
    identity = Identity(
        kind="session",
        name=str(session.get("name") or ""),
        username=session.get("username"),
    )
    request.state.identity = identity
    return identity


def websocket_session(websocket: HTTPConnection, settings: Settings) -> Identity | None:
    """Come require_auth, per i WebSocket (il telecomando): l'identità o None.

    Il controllo dell'origine vale anche qui, con qualunque metodo: un WebSocket non è
    soggetto a CORS, e senza questo controllo un'altra pagina di jshep.xyz aperta nello
    stesso browser potrebbe pilotare lo studio con il cookie dell'utente.
    I token con scope non pilotano lo studio: restano fuori dal telecomando.
    """
    try:
        check_bearer_blocked(websocket)
    except HTTPException:
        return None
    token = _bearer(websocket)
    if token is not None:
        identity = _identify_bearer(websocket, token, settings)
        return identity if identity is not None and identity.kind == "admin" else None
    session = read_session(websocket)
    if session is None:
        return None
    if not _same_origin(websocket, settings):
        log.warning(
            "WebSocket da un'altra origine rifiutato",
            extra={"client": client_key(websocket), "path": websocket.url.path},
        )
        return None
    return Identity(
        kind="session", name=str(session.get("name") or ""), username=session.get("username")
    )


def check_login_rate(request: Request) -> None:
    """Limite ai login AnkiWeb: per IP e globale (l'account è uno solo)."""
    limiter: RateLimiter = request.app.state.login_limiter
    for key in (client_key(request), "*"):
        retry = limiter.retry_after(key)
        if retry:
            raise _too_many(retry, "di login")


def record_login_attempt(request: Request, ok: bool) -> None:
    limiter: RateLimiter = request.app.state.login_limiter
    if ok:
        limiter.reset(client_key(request))
        return
    limiter.hit(client_key(request))
    limiter.hit("*")


# ---- header -----------------------------------------------------------------

_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# i media sono contenuto dell'utente: se qualcuno apre direttamente un .svg o un
# .html della collezione, gira in una sandbox senza script e senza la nostra origine
_MEDIA_CSP = "default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; sandbox"


def is_api_path(path: str) -> bool:
    """Le risposte "da API" (JSON, mai la PWA): /api, il server MCP e i metadati OAuth."""
    return (
        path == "/api"
        or path.startswith("/api/")
        or path == "/mcp"
        or path.startswith("/mcp/")
        or path.startswith("/.well-known/")
    )


def security_headers(request: Request, headers) -> None:
    path = request.url.path
    if request.url.scheme == "https":
        headers.setdefault("Strict-Transport-Security", "max-age=15552000")
    if not is_api_path(path):
        # la PWA (app/web.py): la CSP della shell la mette PWAFiles su index.html,
        # la cache dipende dal file. Niente iframe: la PWA non va incorniciata da altri.
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("Referrer-Policy", "no-referrer")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    headers.setdefault(
        "Content-Security-Policy", _MEDIA_CSP if path.startswith("/api/media/") else _API_CSP
    )
    if "cache-control" not in headers:
        headers["Cache-Control"] = "no-store"
