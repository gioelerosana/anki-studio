"""Accesso a `/mcp` (docs/PIANO-HUB.md, «Autenticazione di /mcp»).

Due modi, in un solo posto:

1. **Bearer `ask_…`** (token degli agenti) e il vecchio `ANKI_API_TOKEN`: gli stessi di `/api`,
   con gli stessi scope e lo stesso limite ai tentativi sbagliati (`check_blocked`,
   `record_auth_failure`).
2. **OAuth con Authentik** per l'app Claude: un JWT firmato da un SECONDO provider Authentik.
   Qui sì si verifica la firma (a differenza dell'ID token del login della PWA, che arriva
   direttamente dal token endpoint): il token arriva da un client esterno, quindi vale solo
   quanto la firma. Chiavi dal JWKS dell'issuer, solo algoritmi asimmetrici (RS256, ES256).

Il cookie di sessione della PWA NON vale su `/mcp`: qui non si leggono nemmeno i cookie (niente
CSRF da gestire, nessuna autorità implicita), e un token nella query string si ignora.

Un `401` porta sempre `WWW-Authenticate` con `resource_metadata` (RFC 9728): è così che Claude
scopre l'authorization server. Mai un redirect: il client lo seguirebbe verso una pagina HTML.

**Chi è l'utente.** Il `sub` di Authentik è opaco, quindi ci si identifica con
`preferred_username` (poi `email`) e si applicano `ANKI_OIDC_ALLOWED_USERS/_GROUPS` con la stessa
funzione della PWA (`oidc.authorize_claims`). Se i claim servono (liste impostate) ma nel JWT non
ci sono, la richiesta è rifiutata con un errore che lo dice; NON si chiama lo userinfo endpoint:
sarebbe una chiamata di rete in più sul percorso della richiesta, e basta aggiungere gli scope
`profile`/`email` al provider per averli nel token. Senza liste decide Authentik (policy
dell'applicazione) e l'utente può anche mancare.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Literal
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings
from .oidc import OIDCError, authorize_claims
from .security import Identity, _bearer, check_blocked, match_bearer, record_auth_failure
from .tokens import TOKEN_PREFIX

log = logging.getLogger(__name__)

# gli scope che Claude deve chiedere ad Authentik (compaiono nei metadati e in WWW-Authenticate)
OAUTH_SCOPES = ["openid", "profile", "email", "offline_access"]
# solo firme asimmetriche: con `none` o HS* (chiave condivisa) basterebbe la chiave pubblica,
# che è pubblica, per falsificare un token (algorithm confusion)
ALGORITHMS = ("RS256", "ES256")
_TOKEN_TYPES = {"jwt", "at+jwt", "application/at+jwt"}
_LEEWAY_S = 60
_FETCH_TIMEOUT_S = 5
_MAX_FETCH_BYTES = 1024 * 1024
_DISCOVERY_TTL_S = 3600
_JWKS_TTL_S = 3600
# un `kid` sconosciuto fa ricaricare il JWKS (rotazione delle chiavi), ma al massimo una volta
# a minuto: senza limite chiunque, con token inventati, ci farebbe martellare Authentik
_JWKS_RELOAD_MIN_S = 60
# dopo un errore di rete non si riprova per un po': i thread della richiesta non devono
# restare appesi a un issuer irraggiungibile, uno dopo l'altro
_FAILURE_BACKOFF_S = 10

# nome dell'agente (tag `agent::claude`) delle note create via OAuth
OAUTH_AGENT_NAME = "claude"


class McpAuthError(Exception):
    """`kind`: invalid = token non valido (401, conta come tentativo sbagliato);
    forbidden = firma valida ma utente non ammesso (403); unavailable = non si può verificare
    adesso (issuer o JWKS irraggiungibili: 503, non è colpa del client)."""

    def __init__(self, kind: Literal["invalid", "forbidden", "unavailable"], detail: str) -> None:
        super().__init__(detail)
        self.kind = kind


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None  # un 3xx diventa un errore: si parla solo con l'URL dichiarato


def _fetch_json(url: str) -> dict:
    """GET di un documento JSON dell'issuer (discovery, JWKS). Sostituito nei test, che non
    fanno rete. Solo https, timeout corto, nessun redirect, dimensione limitata."""
    if not url.startswith("https://"):
        raise McpAuthError("unavailable", f"URL non https: {url}")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "anki-studio"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=_FETCH_TIMEOUT_S) as res:  # noqa: S310 - URL dell'issuer in config
            raw = res.read(_MAX_FETCH_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise McpAuthError("unavailable", f"{url}: {e}") from None
    if len(raw) > _MAX_FETCH_BYTES:
        raise McpAuthError("unavailable", f"{url}: risposta troppo grande")
    try:
        data = json.loads(raw)
    except ValueError:
        raise McpAuthError("unavailable", f"{url}: JSON non valido") from None
    if not isinstance(data, dict):
        raise McpAuthError("unavailable", f"{url}: JSON inatteso")
    return data


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme, parts.netloc.lower()


class OAuthVerifier:
    """Verifica i JWT di Authentik. Sincrono (rete bloccante per discovery e JWKS, solo quando
    la cache è scaduta o arriva un `kid` nuovo): l'ASGI lo chiama dal threadpool."""

    def __init__(self, settings: Settings) -> None:
        assert settings.anki_mcp_oidc_issuer and settings.anki_mcp_oidc_client_id
        self.issuer = settings.anki_mcp_oidc_issuer
        self.client_id = settings.anki_mcp_oidc_client_id
        self.review = settings.anki_mcp_oauth_review
        self.allowed_users = settings.allowed_users
        self.allowed_groups = settings.allowed_groups
        self._lock = threading.Lock()
        self._jwks_uri: str | None = None
        self._jwks_uri_at = 0.0
        self._keys: dict[str | None, jwt.PyJWK] | None = None
        self._keys_at = 0.0
        self._last_reload = float("-inf")
        self._backoff_until = 0.0

    # ---- chiavi ----------------------------------------------------------------------

    def _discover(self) -> str:
        now = time.monotonic()
        if self._jwks_uri and now - self._jwks_uri_at < _DISCOVERY_TTL_S:
            return self._jwks_uri
        doc = _fetch_json(self.issuer.rstrip("/") + "/.well-known/openid-configuration")
        # l'issuer dichiarato deve essere quello configurato (OIDC Discovery §4.3)
        if str(doc.get("issuer", "")).rstrip("/") != self.issuer.rstrip("/"):
            raise McpAuthError("unavailable", f"issuer della discovery diverso: {doc.get('issuer')!r}")
        uri = str(doc.get("jwks_uri", ""))
        # protezione SSRF minima: le chiavi vengono dall'issuer configurato e da nessun altro
        if _origin(uri) != _origin(self.issuer) or not uri.startswith("https://"):
            raise McpAuthError("unavailable", f"jwks_uri non appartiene all'issuer: {uri!r}")
        self._jwks_uri, self._jwks_uri_at = uri, now
        return uri

    def _load_keys(self) -> dict[str | None, jwt.PyJWK]:
        """Scarica e legge il JWKS. Solo chiavi di firma RSA ed EC P-256; le altre si saltano."""
        data = _fetch_json(self._discover())
        keys: dict[str | None, jwt.PyJWK] = {}
        for raw in data.get("keys", []) if isinstance(data.get("keys"), list) else []:
            if not isinstance(raw, dict) or raw.get("use") not in (None, "sig"):
                continue
            if raw.get("kty") == "EC" and raw.get("crv") != "P-256":
                continue
            if raw.get("kty") not in ("RSA", "EC"):
                continue
            try:
                keys[raw.get("kid")] = jwt.PyJWK(raw)
            except jwt.PyJWTError:
                log.warning("Chiave del JWKS non leggibile", extra={"kid": raw.get("kid")})
        if not keys:
            raise McpAuthError("unavailable", "il JWKS non contiene chiavi di firma utilizzabili")
        return keys

    def _refresh(self, *, forced: bool) -> None:
        """Aggiorna la cache delle chiavi, con un solo thread alla volta (gli altri aspettano e
        trovano la cache già fresca). In caso di errore si tiene la cache vecchia, se c'è."""
        with self._lock:
            now = time.monotonic()
            if forced:
                if now - self._last_reload < _JWKS_RELOAD_MIN_S:
                    return
            elif self._keys is not None and now - self._keys_at < _JWKS_TTL_S:
                return  # un altro thread l'ha già fatto mentre aspettavamo il lock
            if now < self._backoff_until:
                if self._keys is None:
                    raise McpAuthError("unavailable", "issuer non raggiungibile (riprovo a breve)")
                return
            self._last_reload = now
            try:
                self._keys, self._keys_at = self._load_keys(), now
            except McpAuthError as e:
                self._backoff_until = now + _FAILURE_BACKOFF_S
                log.warning("JWKS non aggiornato: %s", e)
                if self._keys is None:
                    raise

    def _key_for(self, kid: str | None, alg: str) -> jwt.PyJWK:
        if self._keys is None or time.monotonic() - self._keys_at >= _JWKS_TTL_S:
            self._refresh(forced=False)
        key = self._lookup(kid)
        if key is None:
            # chiave ruotata: una sola ricarica, con limite di frequenza
            self._refresh(forced=True)
            key = self._lookup(kid)
        if key is None:
            raise McpAuthError("invalid", "kid sconosciuto: nessuna chiave del provider ha firmato questo token")
        wanted = "RSA" if alg == "RS256" else "EC"
        if key.key_type != wanted:
            raise McpAuthError("invalid", f"la chiave {kid!r} non è adatta all'algoritmo {alg}")
        return key

    def _lookup(self, kid: str | None) -> jwt.PyJWK | None:
        keys = self._keys or {}
        if kid is not None:
            return keys.get(kid)
        # senza kid si accetta solo un JWKS con una chiave sola: niente tentativi su più chiavi
        return next(iter(keys.values())) if len(keys) == 1 else None

    # ---- verifica ----------------------------------------------------------------------

    def verify(self, token: str) -> dict:
        """I claim di un JWT valido e di un utente ammesso, altrimenti `McpAuthError`."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise McpAuthError("invalid", "token non leggibile") from None
        alg = header.get("alg")
        if alg not in ALGORITHMS:
            raise McpAuthError("invalid", f"algoritmo {alg!r} non ammesso (solo {', '.join(ALGORITHMS)})")
        typ = header.get("typ")
        if typ is not None and str(typ).lower() not in _TOKEN_TYPES:
            raise McpAuthError("invalid", f"tipo di token {typ!r} non ammesso")
        key = self._key_for(header.get("kid"), alg)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=[alg],  # mai l'algoritmo scelto dal token
                audience=self.client_id,  # l'`aud` è il client id del provider, non l'URL della risorsa
                leeway=_LEEWAY_S,
                # iss lo confrontiamo noi (tollerando lo slash finale, come oidc.py)
                options={"require": ["exp", "iss", "aud"], "verify_iss": False},
            )
        except jwt.ExpiredSignatureError:
            raise McpAuthError("invalid", "token scaduto") from None
        except jwt.InvalidAudienceError:
            raise McpAuthError("invalid", "aud del token diverso dal client id configurato") from None
        except jwt.PyJWTError as e:
            # il messaggio di PyJWT non contiene il token: solo il motivo (firma, nbf, iat, …)
            raise McpAuthError("invalid", f"token non valido: {e}") from None
        if str(claims.get("iss", "")).rstrip("/") != self.issuer.rstrip("/"):
            raise McpAuthError("invalid", "iss del token diverso dall'issuer configurato")
        aud = claims.get("aud")
        if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != self.client_id:
            raise McpAuthError("invalid", "azp del token non è questo client")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise McpAuthError("invalid", "sub mancante")
        try:
            authorize_claims(claims, self.allowed_users, self.allowed_groups)
        except OIDCError as e:
            raise McpAuthError("forbidden", str(e)) from None
        return claims

    def identity(self, claims: dict) -> Identity:
        username = claims.get("preferred_username") or claims.get("email")
        return Identity(
            kind="oauth",
            name=OAUTH_AGENT_NAME,
            scope="write",
            review=self.review,
            username=str(username) if username else None,
        )


# ---- risposte --------------------------------------------------------------------------


def metadata_url(settings: Settings) -> str:
    assert settings.anki_public_url
    return settings.anki_public_url.rstrip("/") + "/.well-known/oauth-protected-resource/mcp"


def www_authenticate(settings: Settings, *, invalid: bool) -> str:
    """Il challenge del 401. Con l'OAuth configurato punta ai metadati (è così che Claude trova
    Authentik); senza, ci sono solo i token statici e non c'è niente da scoprire."""
    params = ['error="invalid_token"'] if invalid else []
    if settings.mcp_oauth_enabled:
        params.append(f'resource_metadata="{metadata_url(settings)}"')
        params.append(f'scope="{" ".join(OAUTH_SCOPES)}"')
    return "Bearer " + ", ".join(params) if params else "Bearer"


def protected_resource_metadata(settings: Settings) -> dict:
    """RFC 9728. `resource` è esattamente l'URL che l'utente inserisce in Claude; un solo
    authorization server (Claude usa il primo)."""
    assert settings.mcp_resource_url and settings.anki_mcp_oidc_issuer
    return {
        "resource": settings.mcp_resource_url,
        "authorization_servers": [settings.anki_mcp_oidc_issuer],
        "scopes_supported": list(OAUTH_SCOPES),
        "bearer_methods_supported": ["header"],
    }


class McpAuth:
    """Middleware ASGI davanti all'app MCP dell'SDK: autentica, mette l'identità in
    `scope["state"]["identity"]` (gli strumenti la leggono da lì) e inoltra.

    Fatto a mano e non con il `TokenVerifier` dell'SDK perché qui servono i nostri scope, il
    rate limit e un challenge esatto; e perché l'identità deve essere un `Identity`, la stessa
    della REST. Un cookie non è mai una credenziale: non si guarda."""

    def __init__(self, app: ASGIApp, settings: Settings, verifier: OAuthVerifier | None) -> None:
        self.app = app
        self.settings = settings
        self.verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return  # lifespan e websocket non passano da qui
        request = Request(scope, receive)
        outcome = await self._authenticate(request)
        if isinstance(outcome, Response):
            await outcome(scope, receive, send)
            return
        scope.setdefault("state", {})["identity"] = outcome
        await self.app(scope, receive, send)

    def _reject(self, status: int, detail: str, *, invalid: bool = False) -> Response:
        body: dict[str, str] = {"detail": detail}
        if invalid:
            body["error"] = "invalid_token"
        headers = {"WWW-Authenticate": www_authenticate(self.settings, invalid=invalid)}
        return JSONResponse(body, status_code=status, headers=headers)

    async def _authenticate(self, request: Request) -> Identity | Response:
        try:
            check_blocked(request)
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code, headers=e.headers)
        token = _bearer(request)
        if token is None:
            return self._reject(401, "Accesso richiesto")

        identity = match_bearer(request, token, self.settings)
        if identity is None and self.verifier is not None and self._looks_like_jwt(token):
            try:
                claims = await run_in_threadpool(self.verifier.verify, token)
            except McpAuthError as e:
                if e.kind == "unavailable":
                    log.warning("Verifica JWT impossibile: %s", e)
                    return JSONResponse(
                        {"detail": "Authentik non raggiungibile: riprova tra poco"},
                        status_code=503,
                        headers={"Retry-After": "10"},
                    )
                if e.kind == "forbidden":
                    log.warning("Utente OAuth non ammesso: %s", e, extra={"client": _client(request)})
                    return JSONResponse({"detail": f"Utente non ammesso: {e}"}, status_code=403)
                log.info("JWT rifiutato: %s", e)
            else:
                return self.verifier.identity(claims)
        if identity is None:
            # token statico sbagliato o JWT non valido: un tentativo sbagliato per il rate limit
            record_auth_failure(request, "Token di /mcp")
            return self._reject(401, "Token non valido", invalid=True)
        return identity

    @staticmethod
    def _looks_like_jwt(token: str) -> bool:
        return not token.startswith(TOKEN_PREFIX) and token.count(".") == 2


def _client(request: Request) -> str | None:
    return request.client.host if request.client else None
