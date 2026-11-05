"""Login della PWA con Authentik (OIDC) e sessione in un cookie HttpOnly.

La PWA non chiede più nessun token: all'avvio chiama GET /api/auth/me e, se non
c'è una sessione, naviga su /api/auth/login. Da lì Authentik (che spesso ha già
una sessione e non chiede niente) rimanda a /api/auth/callback, che imposta il
cookie e torna alla pagina di partenza. Gli errori tornano alla PWA come
`?auth_error=<codice>`, senza dettagli: quelli restano nei log.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response

from ..config import Settings, get_settings
from ..oidc import OIDCClient, OIDCError
from ..schemas import AuthLogout, AuthUser
from ..security import (
    LOGIN_COOKIE,
    SESSION_COOKIE,
    Signer,
    check_blocked,
    cookie_secure,
    record_auth_failure,
    require_auth,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_MAX_AGE_S = 600
# `next` finisce nel cookie del login: oltre i ~4 KB il browser lo scarterebbe
_NEXT_MAX_LEN = 512
# cookie delle versioni con il token: tolti al login e al logout
_LEGACY_COOKIES = (("anki_media", "/api/media"), ("anki_token", "/api"))


def _safe_next(value: str | None) -> str:
    """Solo percorsi della PWA: niente redirect verso altri siti né verso l'API."""
    if (
        not value
        or len(value) > _NEXT_MAX_LEN
        or not value.startswith("/")
        or value.startswith(("//", "/\\", "/api/"))
        or any(c in value for c in "\r\n\\")
    ):
        return "/"
    return value


def _back(next_path: str, error: str | None = None) -> RedirectResponse:
    url = next_path
    if error:
        parts = urlsplit(next_path)
        query = [(k, v) for k, v in parse_qsl(parts.query) if k != "auth_error"]
        query.append(("auth_error", error))
        url = urlunsplit(("", "", parts.path, urlencode(query), parts.fragment))
    # 303: il browser torna con un GET, qualunque fosse il metodo
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


def _signer(request: Request) -> Signer:
    return request.app.state.signer


def _oidc(request: Request) -> OIDCClient | None:
    return getattr(request.app.state, "oidc", None)


def _clear_legacy(response: Response) -> None:
    for name, path in _LEGACY_COOKIES:
        response.delete_cookie(name, path=path)


def _open_session(request: Request, response: Response, settings: Settings, user: dict) -> None:
    max_age = int(settings.anki_session_days * 86400)
    response.set_cookie(
        SESSION_COOKIE,
        _signer(request).dumps("session", user, max_age),
        max_age=max_age,
        httponly=True,
        secure=cookie_secure(request),
        # Lax e non Strict: il primo caricamento dopo il ritorno da Authentik è una
        # navigazione da un altro host. Le modifiche sono protette da _same_origin.
        samesite="lax",
        path="/",
    )
    _clear_legacy(response)


@router.get("/login", include_in_schema=False)
def login(request: Request, next: str | None = None, settings: Settings = Depends(get_settings)):
    """Navigazione (non fetch): porta su Authentik e poi di nuovo a `next`."""
    next_path = _safe_next(next)
    oidc = _oidc(request)
    if oidc is None:
        if not settings.anki_dev_login:
            log.error("Login richiesto ma OIDC non è configurato (ANKI_OIDC_*)")
            return _back(next_path, "unconfigured")
        response = _back(next_path)
        _open_session(request, response, settings, {"sub": "dev", "name": "Sviluppo"})
        return response
    try:
        start = oidc.start()
    except OIDCError as e:
        log.error("Login: provider non disponibile: %s", e)
        return _back(next_path, e.code)
    response = RedirectResponse(start.url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        LOGIN_COOKIE,
        _signer(request).dumps(
            "login",
            {"state": start.state, "nonce": start.nonce, "verifier": start.verifier, "next": next_path},
            _LOGIN_MAX_AGE_S,
        ),
        max_age=_LOGIN_MAX_AGE_S,
        httponly=True,
        secure=cookie_secure(request),
        # il ritorno da Authentik è una navigazione GET di primo livello: Lax basta
        samesite="lax",
        path="/api/auth",
    )
    return response


@router.get("/callback", include_in_schema=False)
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_settings),
):
    oidc = _oidc(request)
    pending = _signer(request).loads("login", request.cookies.get(LOGIN_COOKIE))
    next_path = _safe_next(pending.get("next") if pending else None)

    def fail(code_: str) -> RedirectResponse:
        response = _back(next_path, code_)
        response.delete_cookie(LOGIN_COOKIE, path="/api/auth")
        return response

    if oidc is None:
        return fail("unconfigured")
    try:
        check_blocked(request)
    except HTTPException:
        return fail("blocked")
    if error:
        # es. access_denied: l'utente ha annullato o Authentik non lo autorizza
        log.warning("Login rifiutato da Authentik: %s", error[:64])
        return fail("denied")
    if pending is None:
        # cookie scaduto (più di 10 minuti sulla pagina di login) o assente
        return fail("expired")
    if not state or not code or state != pending["state"]:
        record_auth_failure(request, "State del login")
        return fail("expired")
    try:
        # rotta `def`: la richiesta ad Authentik gira nel threadpool, non nell'event loop
        claims = oidc.finish(code, pending["nonce"], pending["verifier"])
    except OIDCError as e:
        if e.code == "failed":
            record_auth_failure(request, "Login OIDC")
        log.warning("Login non riuscito: %s", e)
        return fail(e.code)
    user = {
        "sub": claims["sub"],
        "name": claims.get("name") or claims.get("preferred_username") or claims["sub"],
        "username": claims.get("preferred_username"),
    }
    log.info("Login", extra={"user": user["username"] or user["sub"]})
    response = _back(next_path)
    response.delete_cookie(LOGIN_COOKIE, path="/api/auth")
    _open_session(request, response, settings, user)
    return response


@router.get("/me", response_model=AuthUser)
def me(user: dict = Depends(require_auth)):
    """Chi è collegato. 401 = nessuna sessione: la PWA va su /api/auth/login."""
    return AuthUser(name=str(user.get("name") or ""), username=user.get("username"))


@router.post("/logout", response_model=AuthLogout)
def logout(request: Request, response: Response):
    """Chiude la sessione di Anki Studio. `logout_url` chiude anche quella di Authentik:
    la PWA ci naviga, altrimenti il prossimo login rientrerebbe senza chiedere niente."""
    if request.headers.get("sec-fetch-site", "same-origin") != "same-origin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Richiesta da un'altra origine")
    response.delete_cookie(SESSION_COOKIE, path="/")
    _clear_legacy(response)
    oidc = _oidc(request)
    return AuthLogout(logout_url=oidc.end_session_url() if oidc else None)
