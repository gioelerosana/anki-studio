"""Accesso a /mcp: 401 con il challenge giusto, metadati OAuth, JWT di Authentik verificati con
un JWKS finto (nessuna rete), token statici con lo stesso rate limit della REST, cookie che non
valgono, Host ammessi e niente redirect."""

import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient

from app import mcp_auth
from app.main import create_app
from app.mcp_auth import McpAuthError

from .conftest import TOKEN
from .test_mcp import call, headers_for, note_args, rpc, text_of

PUBLIC = "https://anki.test"
ISSUER = "https://auth.test/application/o/anki-studio-mcp/"
CLIENT_ID = "anki-mcp-client"
DISCOVERY = ISSUER + ".well-known/openid-configuration"
JWKS_URI = ISSUER + "jwks/"
CHALLENGE = (
    f'Bearer resource_metadata="{PUBLIC}/.well-known/oauth-protected-resource/mcp", '
    'scope="openid profile email offline_access"'
)
INVALID_CHALLENGE = CHALLENGE.replace("Bearer ", 'Bearer error="invalid_token", ', 1)

_RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_EC = ec.generate_private_key(ec.SECP256R1())


def _jwk(public_key, kid: str, alg: str) -> dict:
    algorithm = jwt.algorithms.RSAAlgorithm if alg == "RS256" else jwt.algorithms.ECAlgorithm
    return {**algorithm.to_jwk(public_key, as_dict=True), "kid": kid, "use": "sig", "alg": alg}


class FakeIdp:
    """Il provider Authentik finto: discovery, JWKS e firma dei token. Conta le richieste."""

    def __init__(self):
        self.keys = {"k1": (_RSA, "RS256")}
        self.requests: list[str] = []
        self.down = False

    def jwks(self) -> dict:
        return {"keys": [_jwk(k.public_key(), kid, alg) for kid, (k, alg) in self.keys.items()]}

    def fetch(self, url: str) -> dict:
        self.requests.append(url)
        if self.down:
            raise McpAuthError("unavailable", f"{url}: giù")
        if url == DISCOVERY:
            return {"issuer": ISSUER, "jwks_uri": JWKS_URI}
        if url == JWKS_URI:
            return self.jwks()
        raise AssertionError(f"URL inatteso: {url}")

    def claims(self, **override) -> dict:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "5f3a-opaco",
            "exp": now + 300,
            "iat": now,
            "preferred_username": "joel",
            "email": "joel@example.org",
        }
        claims.update(override)
        return {k: v for k, v in claims.items() if v is not None}

    def token(self, kid="k1", key=None, alg="RS256", typ="at+jwt", **override) -> str:
        key = key or self.keys[kid][0]
        headers = {"kid": kid}
        if typ:
            headers["typ"] = typ
        return jwt.encode(self.claims(**override), key, algorithm=alg, headers=headers)


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def forge(header: dict, claims: dict, sign=None) -> str:
    body = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims).encode())}"
    return f"{body}.{b64(sign(body.encode())) if sign else ''}"


@pytest.fixture
def idp(monkeypatch):
    fake = FakeIdp()
    monkeypatch.setattr(mcp_auth, "_fetch_json", fake.fetch)
    return fake


def make_client(seeded, **overrides):
    settings, did = seeded
    values = {
        "anki_public_url": PUBLIC,
        "anki_mcp_oidc_issuer": ISSUER,
        "anki_mcp_oidc_client_id": CLIENT_ID,
        **overrides,
    }
    return TestClient(create_app(settings.model_copy(update=values)), base_url=PUBLIC)


@pytest.fixture
def oauth_client(seeded, idp):
    with make_client(seeded) as c:
        yield c


def jwt_rpc(client, token, method="tools/list", params=None):
    return rpc(client, method, params, token=token)


def tool_with_jwt(client, token, name, args=None):
    return call(client, name, args, token=token)


# ---- 401 e metadati ------------------------------------------------------------------------------


def test_no_credentials_is_401_with_the_exact_challenge(oauth_client):
    for path in ("/mcp", "/mcp/"):
        r = oauth_client.post(path, json={}, follow_redirects=False)
        assert r.status_code == 401, path
        assert r.headers["www-authenticate"] == CHALLENGE
        assert "location" not in r.headers
    # anche GET e DELETE (flusso SSE e chiusura della sessione): mai redirect, mai 200
    for method in ("GET", "DELETE"):
        r = oauth_client.request(method, "/mcp", follow_redirects=False)
        assert r.status_code == 401 and r.headers["www-authenticate"] == CHALLENGE


def test_wrong_credentials_are_401_with_invalid_token(oauth_client):
    for token in ("ask_inesistente", "sbagliato", "a.b.c", TOKEN + "x"):
        r = oauth_client.post("/mcp", json={}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, token
        assert r.headers["www-authenticate"] == INVALID_CHALLENGE
        assert r.json()["error"] == "invalid_token"
    # uno schema diverso da Bearer è come niente
    r = oauth_client.post("/mcp", json={}, headers={"Authorization": f"Basic {TOKEN}"})
    assert r.status_code == 401 and r.headers["www-authenticate"] == CHALLENGE


def test_challenge_without_oauth_has_no_metadata_pointer(seeded):
    settings, _ = seeded
    with TestClient(create_app(settings)) as c:
        r = c.post("/mcp", json={})
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        r = c.post("/mcp", json={}, headers={"Authorization": "Bearer x"})
        assert r.headers["www-authenticate"] == 'Bearer error="invalid_token"'
        # senza OAuth non ci sono metadati da scoprire
        assert c.get("/.well-known/oauth-protected-resource").status_code == 404
        assert c.get("/.well-known/oauth-protected-resource/mcp").status_code == 404


def test_protected_resource_metadata_is_exact_and_public(oauth_client):
    expected = {
        "resource": f"{PUBLIC}/mcp",
        "authorization_servers": [ISSUER],
        "scopes_supported": ["openid", "profile", "email", "offline_access"],
        "bearer_methods_supported": ["header"],
    }
    for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
        r = oauth_client.get(path, headers={"Authorization": ""})
        assert r.status_code == 200, path
        assert r.json() == expected
        assert r.headers["content-type"].startswith("application/json")
        assert r.headers["access-control-allow-origin"] == "*"
    # il challenge punta esattamente a questo URL
    assert f'resource_metadata="{PUBLIC}/.well-known/oauth-protected-resource/mcp"' in CHALLENGE


def test_metadata_resource_has_no_trailing_slash(seeded, idp):
    with make_client(seeded, anki_public_url=PUBLIC + "/") as c:
        assert c.get("/.well-known/oauth-protected-resource").json()["resource"] == f"{PUBLIC}/mcp"
        assert c.post("/mcp", json={}).headers["www-authenticate"] == CHALLENGE


def test_unknown_well_known_and_mcp_subpaths_are_404(oauth_client):
    for path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration", "/mcp/altro"):
        assert oauth_client.get(path).status_code in (404, 401), path
    assert oauth_client.get("/.well-known/oauth-authorization-server").status_code == 404


def test_mcp_disabled_removes_everything(seeded):
    with make_client(seeded, anki_mcp_enabled=False) as c:
        assert c.post("/mcp", json={}).status_code == 404
        assert c.get("/.well-known/oauth-protected-resource").status_code == 404
        assert c.get("/api/decks", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_mcp_oauth_settings_are_validated(seeded):
    settings, _ = seeded
    with pytest.raises(ValueError, match="https"):
        type(settings)(**{**settings.model_dump(), "anki_public_url": PUBLIC, "anki_mcp_oidc_issuer": "http://auth.test/", "anki_mcp_oidc_client_id": "x"})
    with pytest.raises(ValueError, match="incompleto"):
        type(settings)(**{**settings.model_dump(), "anki_public_url": PUBLIC, "anki_mcp_oidc_issuer": ISSUER})
    with pytest.raises(ValueError, match="incompleto"):
        type(settings)(**{**settings.model_dump(), "anki_mcp_oidc_issuer": ISSUER, "anki_mcp_oidc_client_id": "x"})


# ---- JWT ---------------------------------------------------------------------------------------------


def test_valid_jwt_authenticates_as_claude(oauth_client, idp):
    token = idp.token()
    r, msg = jwt_rpc(oauth_client, token)
    assert r.status_code == 200 and len(msg["result"]["tools"]) == 12
    # identità: scope write, agente `claude`; le note entrano subito, normali
    out = tool_with_jwt(oauth_client, token, "add_notes", {"notes": [note_args("oauth", external_id="o-1")]})["structuredContent"]
    assert out["created"] == 1 and out["operation_id"]
    note = tool_with_jwt(oauth_client, token, "get_note", {"note_id": out["results"][0]["note_id"]})["structuredContent"]
    assert set(note["tags"]) == {"agent::claude", "ext::o-1"}
    # il JWKS si scarica una volta sola, poi è in cache
    assert idp.requests == [DISCOVERY, JWKS_URI]
    # può modificare le proprie note ma non le altre
    mine = tool_with_jwt(oauth_client, token, "update_note", {"note_id": note["id"], "fields": {"Back": "nuovo"}})
    assert not mine["isError"]
    seed = tool_with_jwt(oauth_client, token, "search_notes", {"query": "ser"})["structuredContent"]["notes"][0]["id"]
    assert tool_with_jwt(oauth_client, token, "update_note", {"note_id": seed, "fields": {"Back": "x"}})["isError"]
    # tutti gli strumenti di scrittura
    assert not tool_with_jwt(oauth_client, token, "create_deck", {"name": "Da Claude"})["isError"]


def test_oauth_operations_are_journaled_and_undoable(oauth_client, idp):
    token = idp.token()
    out = tool_with_jwt(oauth_client, token, "add_notes", {"notes": [note_args("annulla")]})["structuredContent"]
    ops = tool_with_jwt(oauth_client, token, "list_operations")["structuredContent"]["operations"]
    assert [o["id"] for o in ops] == [out["operation_id"]] and ops[0]["agent"] == "claude"
    undone = tool_with_jwt(oauth_client, token, "undo_operation", {"operation_id": out["operation_id"]})
    assert undone["structuredContent"]["status"] == "undone" and undone["structuredContent"]["deleted"] == 1


def test_oauth_identity_is_not_valid_on_the_rest_api(oauth_client, idp):
    r = oauth_client.get("/api/decks", headers={"Authorization": f"Bearer {idp.token()}"})
    assert r.status_code == 401


def test_ec_key_is_accepted(oauth_client, idp):
    idp.keys = {"ec1": (_EC, "ES256")}
    r, _ = jwt_rpc(oauth_client, idp.token(kid="ec1", alg="ES256"))
    assert r.status_code == 200


def test_token_type_header(oauth_client, idp):
    for typ in ("JWT", "at+jwt", "application/at+jwt", None):
        assert jwt_rpc(oauth_client, idp.token(typ=typ))[0].status_code == 200, typ
    # un tipo diverso (es. un refresh token o un JWT di un altro uso) no
    assert jwt_rpc(oauth_client, idp.token(typ="refresh+jwt"))[0].status_code == 401


@pytest.mark.parametrize(
    "label,override",
    [
        ("scaduto", {"exp": int(time.time()) - 3600}),
        ("scaduto da poco ma oltre il leeway", {"exp": int(time.time()) - 120}),
        ("iss sbagliato", {"iss": "https://auth.test/application/o/altra-app/"}),
        ("aud sbagliato", {"aud": "un-altro-client"}),
        ("aud = URL della risorsa", {"aud": f"{PUBLIC}/mcp"}),
        ("aud assente", {"aud": None}),
        ("exp assente", {"exp": None}),
        ("nbf nel futuro", {"nbf": int(time.time()) + 3600}),
        ("iat nel futuro", {"iat": int(time.time()) + 3600}),
        ("sub assente", {"sub": None}),
        ("aud multiplo senza azp", {"aud": [CLIENT_ID, "altro"]}),
    ],
)
def test_invalid_claims_are_401(oauth_client, idp, label, override):
    r, _ = jwt_rpc(oauth_client, idp.token(**override))
    assert r.status_code == 401, label
    assert r.headers["www-authenticate"] == INVALID_CHALLENGE


def test_small_clock_skew_is_tolerated(oauth_client, idp):
    now = int(time.time())
    assert jwt_rpc(oauth_client, idp.token(exp=now - 30))[0].status_code == 200
    assert jwt_rpc(oauth_client, idp.token(iat=now + 30))[0].status_code == 200
    assert jwt_rpc(oauth_client, idp.token(iss=ISSUER.rstrip("/")))[0].status_code == 200  # slash finale
    assert jwt_rpc(oauth_client, idp.token(aud=[CLIENT_ID, "altro"], azp=CLIENT_ID))[0].status_code == 200


def test_wrong_signature_is_401(oauth_client, idp):
    assert jwt_rpc(oauth_client, idp.token(key=_OTHER_RSA))[0].status_code == 401
    # firma di una chiave giusta con il kid di un'altra: l'RSA non quadra
    valid = idp.token()
    head, payload, sig = valid.split(".")
    tampered = f"{head}.{b64(json.dumps(idp.claims(preferred_username='intruso')).encode())}.{sig}"
    assert jwt_rpc(oauth_client, tampered)[0].status_code == 401


def test_alg_none_is_401(oauth_client, idp):
    token = forge({"alg": "none", "typ": "JWT", "kid": "k1"}, idp.claims())
    r, _ = jwt_rpc(oauth_client, token)
    assert r.status_code == 401
    # anche con le varianti di maiuscole
    assert jwt_rpc(oauth_client, forge({"alg": "None", "kid": "k1"}, idp.claims()))[0].status_code == 401
    assert jwt_rpc(oauth_client, forge({"alg": "NONE", "kid": "k1"}, idp.claims()))[0].status_code == 401


def test_hs256_signed_with_the_public_key_is_401(oauth_client, idp):
    """Algorithm confusion: HS256 firmato con la chiave pubblica (che è pubblica) come segreto."""
    public_pem = _RSA.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    for secret in (public_pem, json.dumps(idp.jwks()["keys"][0]).encode()):
        token = forge(
            {"alg": "HS256", "typ": "JWT", "kid": "k1"},
            idp.claims(),
            sign=lambda body, s=secret: hmac.new(s, body, hashlib.sha256).digest(),
        )
        assert jwt_rpc(oauth_client, token)[0].status_code == 401
    # nemmeno con un segreto qualunque, né con RS512 o PS256 (non nella lista)
    assert jwt_rpc(oauth_client, forge({"alg": "HS512", "kid": "k1"}, idp.claims(), sign=lambda b: b"x"))[0].status_code == 401
    ps = jwt.encode(idp.claims(), _RSA, algorithm="PS256", headers={"kid": "k1"})
    assert jwt_rpc(oauth_client, ps)[0].status_code == 401
    rs512 = jwt.encode(idp.claims(), _RSA, algorithm="RS512", headers={"kid": "k1"})
    assert jwt_rpc(oauth_client, rs512)[0].status_code == 401


def test_algorithm_must_match_the_key_type(oauth_client, idp):
    """Un token che dichiara ES256 non si verifica con una chiave RSA (e viceversa)."""
    forged = forge({"alg": "ES256", "kid": "k1"}, idp.claims(), sign=lambda b: b"\x00" * 64)
    assert jwt_rpc(oauth_client, forged)[0].status_code == 401


def test_unknown_kid_reloads_the_jwks_once_for_rotation(oauth_client, idp):
    assert jwt_rpc(oauth_client, idp.token())[0].status_code == 200
    assert idp.requests == [DISCOVERY, JWKS_URI]
    # il provider ruota la chiave; la cache è "vecchia" abbastanza da poter ricaricare
    idp.keys = {"k2": (_OTHER_RSA, "RS256")}
    _age_cache(oauth_client)
    assert jwt_rpc(oauth_client, idp.token(kid="k2"))[0].status_code == 200
    assert idp.requests == [DISCOVERY, JWKS_URI, JWKS_URI]
    # la chiave vecchia non c'è più
    assert jwt_rpc(oauth_client, idp.token(kid="k1", key=_RSA))[0].status_code == 401


def test_unknown_kid_without_rotation_does_not_hammer_the_issuer(oauth_client, idp):
    assert jwt_rpc(oauth_client, idp.token())[0].status_code == 200
    before = len(idp.requests)
    # kid inventati a raffica: appena ricaricato, non si ricarica di nuovo
    for i in range(5):
        assert jwt_rpc(oauth_client, unknown_kid(idp, f"inventato{i}"))[0].status_code == 401
    assert len(idp.requests) == before
    # e dopo il limite di frequenza ne basta UNA per tutta la raffica successiva
    _age_cache(oauth_client)
    for i in range(5):
        assert jwt_rpc(oauth_client, unknown_kid(idp, f"altro{i}"))[0].status_code == 401
    assert len(idp.requests) == before + 1


def unknown_kid(idp, kid):
    """Un JWT con un `kid` che il provider non ha mai pubblicato."""
    return jwt.encode(idp.claims(), _RSA, algorithm="RS256", headers={"kid": kid})


def _verifier(client):
    # il verificatore è nel middleware dell'app MCP: lo si raggiunge dall'app ASGI
    return client.app.state.mcp.asgi.verifier


def _age_cache(client):
    v = _verifier(client)
    v._last_reload -= 3600
    v._keys_at -= 10  # ancora valida (TTL 1 h), ma ricaricabile per un kid nuovo


def test_issuer_down_is_503_and_does_not_count_as_a_failed_attempt(seeded, idp):
    idp.down = True
    with make_client(seeded, anki_token_max_failures=3) as c:
        for _ in range(6):
            r, _ = jwt_rpc(c, idp.token())
            assert r.status_code == 503 and r.headers["retry-after"] == "10"
        # il provider torna: tutto riparte, l'IP non è stato bloccato
        idp.down = False
        _verifier(c)._backoff_until = 0
        assert jwt_rpc(c, idp.token())[0].status_code == 200


def test_cached_keys_survive_a_down_issuer(oauth_client, idp):
    assert jwt_rpc(oauth_client, idp.token())[0].status_code == 200
    idp.down = True
    _verifier(oauth_client)._keys_at -= 7200  # cache scaduta: il refresh fallisce, si usa la vecchia
    assert jwt_rpc(oauth_client, idp.token())[0].status_code == 200


def test_jwks_uri_outside_the_issuer_is_refused(seeded, monkeypatch):
    """SSRF minima: le chiavi vengono solo dall'issuer configurato."""
    fetched = []

    def fetch(url):
        fetched.append(url)
        return {"issuer": ISSUER, "jwks_uri": "https://evil.test/jwks"}

    monkeypatch.setattr(mcp_auth, "_fetch_json", fetch)
    with make_client(seeded) as c:
        token = FakeIdp().token()
        r, _ = jwt_rpc(c, token)
        assert r.status_code == 503
    assert fetched == [DISCOVERY]


def test_discovery_issuer_mismatch_is_refused(seeded, monkeypatch):
    monkeypatch.setattr(mcp_auth, "_fetch_json", lambda url: {"issuer": "https://altro.test/", "jwks_uri": JWKS_URI})
    with make_client(seeded) as c:
        assert jwt_rpc(c, FakeIdp().token())[0].status_code == 503


def test_fetch_json_only_speaks_https_without_redirects():
    with pytest.raises(McpAuthError):
        mcp_auth._fetch_json("http://auth.test/jwks")
    with pytest.raises(McpAuthError):
        mcp_auth._fetch_json("file:///etc/passwd")


# ---- utenti ammessi ------------------------------------------------------------------------------------


def test_allowed_users_apply_like_the_pwa_login(seeded, idp):
    with make_client(seeded, anki_oidc_allowed_users="Joel") as c:
        assert jwt_rpc(c, idp.token())[0].status_code == 200  # maiuscole ininfluenti
        r, _ = jwt_rpc(c, idp.token(preferred_username="intruso", email="x@y.z"))
        assert r.status_code == 403 and "non ammesso" in r.json()["detail"]
        # la mail vale come nome, come nel login della PWA
        assert jwt_rpc(c, idp.token(preferred_username=None, email="JOEL"))[0].status_code == 200


def test_allowed_groups(seeded, idp):
    with make_client(seeded, anki_oidc_allowed_groups="anki-users") as c:
        assert jwt_rpc(c, idp.token(groups=["altri", "anki-users"]))[0].status_code == 200
        assert jwt_rpc(c, idp.token(groups=["altri"]))[0].status_code == 403


def test_missing_claims_with_lists_is_a_clear_403(seeded, idp):
    with make_client(seeded, anki_oidc_allowed_users="joel") as c:
        r, _ = jwt_rpc(c, idp.token(preferred_username=None, email=None))
        assert r.status_code == 403
        detail = r.json()["detail"]
        assert "preferred_username" in detail and "scope" in detail


def test_missing_claims_without_lists_is_fine(oauth_client, idp):
    """Senza liste decide Authentik: il JWT valido basta, anche senza preferred_username."""
    assert jwt_rpc(oauth_client, idp.token(preferred_username=None, email=None))[0].status_code == 200


def test_forbidden_user_is_not_a_failed_attempt(seeded, idp):
    with make_client(seeded, anki_oidc_allowed_users="joel", anki_token_max_failures=2) as c:
        for _ in range(5):
            assert jwt_rpc(c, idp.token(preferred_username="intruso", email=None))[0].status_code == 403
        assert jwt_rpc(c, idp.token())[0].status_code == 200


# ---- tentativi sbagliati ---------------------------------------------------------------------------------


def test_invalid_jwts_count_as_failed_attempts(seeded, idp):
    with make_client(seeded, anki_token_max_failures=3) as c:
        for _ in range(3):
            assert jwt_rpc(c, idp.token(aud="altro"))[0].status_code == 401
        # oltre il limite: 429 per tutti, anche con credenziali giuste (come sulla REST)
        r, _ = jwt_rpc(c, idp.token())
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
        r, _ = rpc(c, "tools/list", token=TOKEN)
        assert r.status_code == 429
        assert c.get("/api/decks", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 429


def test_wrong_static_tokens_share_the_rest_limiter(seeded, idp):
    with make_client(seeded, anki_token_max_failures=3) as c:
        # due sbagliati sulla REST e uno su /mcp: il contatore è lo stesso
        for _ in range(2):
            assert c.get("/api/decks", headers={"Authorization": "Bearer ask_sbagliato"}).status_code == 401
        assert c.post("/mcp", json={}, headers={"Authorization": "Bearer ask_sbagliato"}).status_code == 401
        assert c.post("/mcp", json={}, headers=headers_for(TOKEN)).status_code == 429


def test_missing_credentials_are_not_a_failed_attempt(oauth_client):
    for _ in range(30):
        assert oauth_client.post("/mcp", json={}).status_code == 401
    r, _ = rpc(oauth_client, "tools/list", token=TOKEN)
    assert r.status_code == 200


def test_static_tokens_keep_their_scopes_on_mcp(oauth_client):
    created = oauth_client.post(
        "/api/tokens", json={"name": "lettore", "scope": "read"}, headers={"Authorization": f"Bearer {TOKEN}"}
    ).json()
    out = call(oauth_client, "create_deck", {"name": "No"}, token=created["token"])
    assert out["isError"] and "scope «read»" in text_of(out)
    # l'amministratore (ANKI_API_TOKEN) può tutto
    assert not call(oauth_client, "create_deck", {"name": "Si"}, token=TOKEN)["isError"]


# ---- cookie, query string, Host, redirect ---------------------------------------------------------------------


@pytest.fixture
def session_client(seeded, idp):
    settings, _ = seeded
    settings = settings.model_copy(
        update={
            "anki_dev_login": True,
            "anki_api_token": None,
            "anki_public_url": PUBLIC,
            "anki_mcp_oidc_issuer": ISSUER,
            "anki_mcp_oidc_client_id": CLIENT_ID,
        }
    )
    with TestClient(create_app(settings), base_url=PUBLIC) as c:
        c.get("/api/auth/login", follow_redirects=False)
        assert c.get("/api/auth/me").status_code == 200  # la sessione c'è e vale sulla REST
        yield c


def test_session_cookie_does_not_authenticate_mcp(session_client):
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    r = session_client.post("/mcp", json=body, headers={**headers, "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 401 and r.headers["www-authenticate"] == CHALLENGE
    r = session_client.get("/mcp", headers={"Accept": "text/event-stream"})
    assert r.status_code == 401
    # con la sessione e un Bearer sbagliato conta il Bearer
    r = session_client.post("/mcp", json=body, headers={**headers, "Authorization": "Bearer sbagliato"})
    assert r.status_code == 401 and r.headers["www-authenticate"] == INVALID_CHALLENGE


def test_token_in_the_query_string_is_ignored(oauth_client, idp):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    for param in ("access_token", "token", "api_key", "bearer"):
        for value in (TOKEN, idp.token()):
            r = oauth_client.post(f"/mcp?{param}={value}", json=body, headers=headers)
            assert r.status_code == 401, param
    # il token nella query non finisce nel log di accesso: si logga solo il path
    assert jwt_rpc(oauth_client, idp.token())[0].status_code == 200


def test_no_redirect_with_or_without_trailing_slash(oauth_client):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    for path in ("/mcp", "/mcp/"):
        r = oauth_client.post(path, json=body, headers=headers_for(TOKEN), follow_redirects=False)
        assert r.status_code == 200, path
        assert "list_decks" in r.text


def test_host_checks(seeded, idp):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    with make_client(seeded) as c:
        ok = headers_for(TOKEN)
        # il dominio pubblico e localhost (con e senza porta) sono ammessi
        for host in ("anki.test", "anki.test:443", "localhost", "localhost:8000", "127.0.0.1:8000", "[::1]:8000"):
            r = c.post("/mcp", json=body, headers={**ok, "Host": host})
            assert r.status_code == 200, host
        # un altro nome (DNS rebinding) no, con 421
        r = c.post("/mcp", json=body, headers={**ok, "Host": "evil.test"})
        assert r.status_code == 421
        # e un Origin di un altro sito no (un browser su un'altra pagina): 403
        r = c.post("/mcp", json=body, headers={**ok, "Origin": "https://evil.test"})
        assert r.status_code == 403
        r = c.post("/mcp", json=body, headers={**ok, "Origin": PUBLIC})
        assert r.status_code == 200


def test_host_check_is_off_without_a_public_url(seeded):
    """Senza ANKI_PUBLIC_URL (sviluppo) ogni richiesta comunque deve avere un Bearer."""
    settings, _ = seeded
    with TestClient(create_app(settings), base_url="http://192.168.1.5:8000") as c:
        r, _ = rpc(c, "tools/list", token=TOKEN)
        assert r.status_code == 200


def test_security_headers_do_not_break_mcp(oauth_client):
    r = oauth_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, headers=headers_for(TOKEN))
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "no-cache" in r.headers["cache-control"] or "no-store" in r.headers["cache-control"]
    assert "content-encoding" not in r.headers
    r = oauth_client.post("/mcp", json={})
    assert r.headers["cache-control"] == "no-store"


def test_body_limit_still_applies_before_authentication(oauth_client):
    r = oauth_client.post("/mcp", content=b"x" * (51 * 1024 * 1024), headers={"Content-Type": "application/json"})
    assert r.status_code == 413
