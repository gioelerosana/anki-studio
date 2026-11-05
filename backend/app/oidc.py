"""Client OIDC (Authorization Code + PKCE) verso Authentik, lato server.

Il backend è un client *confidenziale* (pattern "backend for frontend"): la PWA
non vede mai codici né token, solo il cookie di sessione HttpOnly che il backend
imposta alla fine del login. Su iPad è anche l'unico flusso che regge la PWA
installata: è una navigazione normale, senza popup né token in localStorage.

Niente librerie in più (l'immagine ha le dipendenze con hash): basta la stdlib.
L'ID token arriva direttamente dal token endpoint dell'issuer su TLS, e per questo
caso OIDC Core (§3.1.3.7, punto 6) ammette la validazione TLS al posto della firma;
gli altri controlli (iss, aud, azp, exp, nonce) li facciamo tutti.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .config import Settings

log = logging.getLogger(__name__)

_TIMEOUT_S = 10
_DISCOVERY_TTL_S = 3600
# tolleranza sugli orologi per exp/iat
_LEEWAY_S = 120


class OIDCError(Exception):
    """Login non riuscito. `code` finisce nell'URL di ritorno (?auth_error=…) e la PWA
    lo traduce in un messaggio; il dettaglio resta solo nei log."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _http_json(url: str, data: dict[str, str] | None = None, auth: tuple[str, str] | None = None) -> dict:
    """GET (o POST form-encoded se c'è `data`) e risposta JSON. Sostituito nei test."""
    headers = {"Accept": "application/json", "User-Agent": "anki-studio"}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if auth is not None:
        # client_secret_basic: id e secret vanno codificati prima (RFC 6749 §2.3.1)
        pair = f"{urllib.parse.quote(auth[0], safe='')}:{urllib.parse.quote(auth[1], safe='')}"
        headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as res:  # noqa: S310 - URL dalla config
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        # il corpo di un errore OAuth è {"error": …, "error_description": …}: niente segreti
        try:
            err = json.loads(e.read())
        except ValueError:
            err = {}
        raise OIDCError("failed", f"HTTP {e.code} da {url}: {err.get('error', '')}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise OIDCError("unreachable", f"{url}: {e}") from None


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwt_claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise OIDCError("failed", "ID token non leggibile") from None
    if not isinstance(data, dict):
        raise OIDCError("failed", "ID token non valido")
    return data


@dataclass
class LoginStart:
    url: str
    state: str
    nonce: str
    verifier: str


class OIDCClient:
    def __init__(self, settings: Settings) -> None:
        assert settings.anki_oidc_issuer and settings.anki_oidc_client_id
        assert settings.anki_oidc_client_secret
        self.issuer = settings.anki_oidc_issuer
        if not self.issuer.startswith("https://") and not _local(self.issuer):
            # il token endpoint è l'unica garanzia sull'ID token (vedi sopra): solo TLS
            raise ValueError("ANKI_OIDC_ISSUER deve essere https://")
        self.client_id = settings.anki_oidc_client_id
        self._secret = settings.anki_oidc_client_secret
        self.redirect_uri = settings.redirect_uri
        self.scopes = settings.anki_oidc_scopes
        self.allowed_users = settings.allowed_users
        self.allowed_groups = settings.allowed_groups
        self._discovery: dict | None = None
        self._discovery_at = 0.0
        self._lock = threading.Lock()

    # ---- discovery -----------------------------------------------------------

    def discovery(self) -> dict:
        with self._lock:
            if self._discovery and time.monotonic() - self._discovery_at < _DISCOVERY_TTL_S:
                return self._discovery
        url = self.issuer.rstrip("/") + "/.well-known/openid-configuration"
        doc = _http_json(url)
        # l'issuer dichiarato deve essere quello configurato (OIDC Discovery §4.3)
        if str(doc.get("issuer", "")).rstrip("/") != self.issuer.rstrip("/"):
            raise OIDCError("failed", f"issuer della discovery diverso: {doc.get('issuer')!r}")
        for key in ("authorization_endpoint", "token_endpoint"):
            if not str(doc.get(key, "")).startswith("https://") and not _local(doc.get(key)):
                raise OIDCError("failed", f"{key} mancante o non https")
        with self._lock:
            self._discovery, self._discovery_at = doc, time.monotonic()
        return doc

    def end_session_url(self) -> str | None:
        try:
            return self.discovery().get("end_session_endpoint") or None
        except OIDCError:
            return None

    # ---- flusso ------------------------------------------------------------

    def start(self) -> LoginStart:
        doc = self.discovery()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "scope": self.scopes,
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return LoginStart(f"{doc['authorization_endpoint']}?{query}", state, nonce, verifier)

    def finish(self, code: str, nonce: str, verifier: str) -> dict:
        """Scambia il codice e restituisce i claim dell'utente, già controllati."""
        doc = self.discovery()
        tokens = _http_json(
            doc["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": verifier,
            },
            auth=(self.client_id, self._secret),
        )
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise OIDCError("failed", "nessun id_token nella risposta")
        claims = _jwt_claims(id_token)
        self._validate(claims, nonce, doc)
        self._authorize(claims)
        return claims

    def _validate(self, claims: dict, nonce: str, doc: dict) -> None:
        now = time.time()
        if str(claims.get("iss", "")).rstrip("/") != str(doc["issuer"]).rstrip("/"):
            raise OIDCError("failed", "iss dell'ID token diverso dall'issuer")
        aud = claims.get("aud")
        auds = aud if isinstance(aud, list) else [aud]
        if self.client_id not in auds:
            raise OIDCError("failed", "aud dell'ID token non è questo client")
        if len(auds) > 1 and claims.get("azp") != self.client_id:
            raise OIDCError("failed", "azp dell'ID token non è questo client")
        exp = claims.get("exp")
        if not isinstance(exp, (int, float)) or exp + _LEEWAY_S < now:
            raise OIDCError("failed", "ID token scaduto")
        iat = claims.get("iat")
        if isinstance(iat, (int, float)) and iat - _LEEWAY_S > now:
            raise OIDCError("failed", "ID token emesso nel futuro")
        if not isinstance(claims.get("nonce"), str) or not secrets.compare_digest(
            claims["nonce"], nonce
        ):
            raise OIDCError("failed", "nonce dell'ID token diverso")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise OIDCError("failed", "sub mancante")

    def _authorize(self, claims: dict) -> None:
        if not self.allowed_users and not self.allowed_groups:
            return
        names = {
            str(claims[k]).lower() for k in ("preferred_username", "email") if claims.get(k)
        }
        groups = claims.get("groups")
        groups = {str(g) for g in groups} if isinstance(groups, list) else set()
        if names & self.allowed_users or groups & self.allowed_groups:
            return
        raise OIDCError("forbidden", f"utente {claims.get('preferred_username')!r} non ammesso")


def _local(url: object) -> bool:
    """Solo per i test e lo sviluppo: un provider su http://localhost."""
    return isinstance(url, str) and url.startswith(("http://localhost", "http://127.0.0.1"))
