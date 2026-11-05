"""Autenticazione della PWA, limiti ai tentativi e header di sicurezza."""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import secrets
import threading
import time
from collections import deque

from fastapi import Depends, HTTPException, Request, status

from .config import Settings, get_settings

log = logging.getLogger(__name__)

COOKIE_NAME = "anki_media"


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


def client_key(request: Request) -> str:
    # dietro nginx/Traefik l'IP vero arriva da X-Forwarded-For, che uvicorn
    # applica solo se il proxy è fidato (FORWARDED_ALLOW_IPS, vedi Dockerfile)
    return request.client.host if request.client else "unknown"


def _too_many(retry: int, what: str) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        f"Troppi tentativi {what}: riprova tra {retry} s",
        headers={"Retry-After": str(retry)},
    )


def media_cookie_value(settings: Settings) -> str:
    """Il cookie non contiene il token: è un valore derivato che apre solo i media."""
    return hmac.new(
        settings.anki_api_token.encode(), b"anki-studio-media-cookie-v1", hashlib.sha256
    ).hexdigest()


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _check(request: Request, ok: bool, presented: bool) -> None:
    limiter: RateLimiter = request.app.state.token_limiter
    key = client_key(request)
    # bloccato anche con il token giusto: altrimenti chi indovina se ne accorgerebbe
    retry = limiter.retry_after(key)
    if retry:
        raise _too_many(retry, "con un token sbagliato")
    if not ok:
        # conta solo i tentativi veri: un <img> senza cookie non sta indovinando niente
        if presented:
            limiter.hit(key)
        log.warning("Token non valido", extra={"client": key, "path": request.url.path})
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token mancante o non valido",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_token(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Accetta solo `Authorization: Bearer <token>`."""
    token = _bearer(request)
    ok = token is not None and secrets.compare_digest(token, settings.anki_api_token)
    _check(request, ok, presented=token is not None)


def require_token_or_media_cookie(
    request: Request, settings: Settings = Depends(get_settings)
) -> None:
    """Per i media: i tag <img>/<audio> delle carte non possono mandare header, quindi
    va bene anche il cookie impostato da POST /api/auth/session."""
    token = _bearer(request)
    cookie = request.cookies.get(COOKIE_NAME)
    if token is not None:
        ok = secrets.compare_digest(token, settings.anki_api_token)
    else:
        ok = cookie is not None and secrets.compare_digest(cookie, media_cookie_value(settings))
    _check(request, ok, presented=token is not None or cookie is not None)


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
