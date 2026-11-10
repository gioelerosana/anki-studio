"""Sessioni della PWA, limiti ai tentativi e header di sicurezza."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import secrets
import threading
import time
from collections import deque

from fastapi import Depends, HTTPException, Request, status
from starlette.requests import HTTPConnection

from .config import Settings, get_settings

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
    limiter: RateLimiter = request.app.state.token_limiter
    # bloccato anche con credenziali giuste: altrimenti chi indovina se ne accorgerebbe
    retry = limiter.retry_after(client_key(request))
    if retry:
        raise _too_many(retry, "con credenziali sbagliate")


def record_auth_failure(request: HTTPConnection, what: str) -> None:
    key = client_key(request)
    request.app.state.token_limiter.hit(key)
    log.warning("%s non valido", what, extra={"client": key, "path": request.url.path})


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


def require_auth(request: Request, settings: Settings = Depends(get_settings)) -> dict:
    """Sessione OIDC (cookie HttpOnly) o, per script e test, `Authorization: Bearer`.

    Vale anche per i media: <img> e <audio> delle carte mandano il cookie da sé.
    """
    check_blocked(request)
    token = _bearer(request)
    if token is not None:
        expected = settings.anki_api_token
        if expected is None:
            # nessun token da indovinare: è la PWA di prima (in cache) con il token vecchio,
            # che non deve far bloccare l'IP proprio mentre passa al login con Authentik
            raise _unauthorized()
        if not secrets.compare_digest(token, expected):
            record_auth_failure(request, "Token")
            raise _unauthorized()
        return {"sub": "api-token", "name": "Token dell'API"}
    session = read_session(request)
    if session is None:
        raise _unauthorized()
    if request.method not in _SAFE_METHODS and not _same_origin(request, settings):
        log.warning(
            "Richiesta da un'altra origine rifiutata",
            extra={"client": client_key(request), "path": request.url.path},
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Richiesta da un'altra origine")
    return session


def websocket_session(websocket: HTTPConnection, settings: Settings) -> dict | None:
    """Come require_auth, per i WebSocket (il telecomando): la sessione o None.

    Il controllo dell'origine vale anche qui, con qualunque metodo: un WebSocket non è
    soggetto a CORS, e senza questo controllo un'altra pagina di jshep.xyz aperta nello
    stesso browser potrebbe pilotare lo studio con il cookie dell'utente.
    """
    try:
        check_blocked(websocket)
    except HTTPException:
        return None
    token = _bearer(websocket)
    if token is not None:
        expected = settings.anki_api_token
        if expected is None:
            return None
        if not secrets.compare_digest(token, expected):
            record_auth_failure(websocket, "Token")
            return None
        return {"sub": "api-token", "name": "Token dell'API"}
    session = read_session(websocket)
    if session is None:
        return None
    if not _same_origin(websocket, settings):
        log.warning(
            "WebSocket da un'altra origine rifiutato",
            extra={"client": client_key(websocket), "path": websocket.url.path},
        )
        return None
    return session


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


def security_headers(request: Request, headers) -> None:
    path = request.url.path
    if request.url.scheme == "https":
        headers.setdefault("Strict-Transport-Security", "max-age=15552000")
    if path != "/api" and not path.startswith("/api/"):
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
