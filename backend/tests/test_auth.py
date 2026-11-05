"""Login OIDC con un provider finto: discovery e token endpoint sostituiti in app.oidc."""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import oidc as oidc_mod
from app.config import Settings
from app.main import create_app

ISSUER = "https://auth.test/application/o/anki-studio/"
CLIENT_ID = "anki-studio"
SECRET = "segreto-del-client-abcdefghij"


def _b64(data: dict | bytes) -> str:
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class FakeProvider:
    """Ricorda l'ultima richiesta di autorizzazione e risponde come Authentik."""

    def __init__(self) -> None:
        self.authorize: dict[str, str] = {}
        self.claims: dict = {}
        self.token_requests: list[dict] = []

    def __call__(self, url, data=None, auth=None):
        if url == ISSUER.rstrip("/") + "/.well-known/openid-configuration":
            return {
                "issuer": ISSUER,
                "authorization_endpoint": "https://auth.test/application/o/authorize/",
                "token_endpoint": "https://auth.test/application/o/token/",
                "end_session_endpoint": f"{ISSUER}end-session/",
            }
        assert url == "https://auth.test/application/o/token/"
        assert auth == (CLIENT_ID, SECRET)
        self.token_requests.append(data)
        if data["code"] != "codice-buono":
            raise oidc_mod.OIDCError("failed", "invalid_grant")
        # PKCE: il verifier deve corrispondere alla challenge dell'autorizzazione
        challenge = _b64(hashlib.sha256(data["code_verifier"].encode()).digest())
        assert challenge == self.authorize["code_challenge"]
        assert data["redirect_uri"] == "https://anki.test/api/auth/callback"
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "hash-utente",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "nonce": self.authorize["nonce"],
            "name": "Joe",
            "preferred_username": "joe",
            "groups": ["Studenti"],
            **self.claims,
        }
        return {"id_token": f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.firma", "access_token": "x"}


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(oidc_mod, "_http_json", fake)
    return fake


def _settings(seeded, **extra) -> Settings:
    settings, _ = seeded
    return settings.model_copy(
        update={
            "anki_api_token": None,
            "anki_public_url": "https://anki.test",
            "anki_oidc_issuer": ISSUER,
            "anki_oidc_client_id": CLIENT_ID,
            "anki_oidc_client_secret": SECRET,
            **extra,
        }
    )


@pytest.fixture
def app_client(seeded, provider):
    with TestClient(create_app(_settings(seeded)), base_url="https://anki.test") as c:
        yield c


def _login(c: TestClient, provider: FakeProvider, next_path="/#/study/5", code="codice-buono", state=None):
    r = c.get("/api/auth/login", params={"next": next_path}, follow_redirects=False)
    assert r.status_code == 303
    url = urlsplit(r.headers["location"])
    assert url.netloc == "auth.test"
    provider.authorize = {k: v[0] for k, v in parse_qs(url.query).items()}
    return c.get(
        "/api/auth/callback",
        params={"code": code, "state": state or provider.authorize["state"]},
        follow_redirects=False,
    )


def test_login_flow(app_client: TestClient, provider: FakeProvider):
    assert app_client.get("/api/decks").status_code == 401
    assert app_client.get("/api/auth/me").status_code == 401

    r = _login(app_client, provider)
    q = provider.authorize
    assert q["client_id"] == CLIENT_ID and q["response_type"] == "code"
    assert q["code_challenge_method"] == "S256" and q["scope"] == "openid profile email"
    assert q["redirect_uri"] == "https://anki.test/api/auth/callback"

    assert r.status_code == 303 and r.headers["location"] == "/#/study/5"
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("anki_studio_session="))
    assert "HttpOnly" in session and "Secure" in session and "samesite=lax" in session.lower()
    assert "Path=/" in session

    assert app_client.get("/api/auth/me").json() == {"name": "Joe", "username": "joe"}
    assert app_client.get("/api/decks").status_code == 200
    # le immagini delle carte passano con lo stesso cookie
    assert app_client.get("/api/media/pic.png").content == b"\x89PNG fake"


def test_login_cookie_is_single_use(app_client: TestClient, provider: FakeProvider):
    _login(app_client, provider)
    # stesso state una seconda volta: il cookie del login è stato tolto
    r = app_client.get(
        "/api/auth/callback",
        params={"code": "codice-buono", "state": provider.authorize["state"]},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/?auth_error=expired"


def test_wrong_state(app_client: TestClient, provider: FakeProvider):
    r = _login(app_client, provider, state="altro")
    assert r.headers["location"] == "/?auth_error=expired#/study/5"
    assert provider.token_requests == []
    assert app_client.get("/api/decks").status_code == 401


def test_bad_code(app_client: TestClient, provider: FakeProvider):
    r = _login(app_client, provider, code="codice-cattivo")
    assert "auth_error=failed" in r.headers["location"]
    assert app_client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "claims",
    [
        {"nonce": "altro"},
        {"aud": "altro-client"},
        {"aud": [CLIENT_ID, "altro"], "azp": "altro"},
        {"iss": "https://evil.test/"},
        {"exp": int(time.time()) - 3600},
    ],
)
def test_id_token_checks(app_client: TestClient, provider: FakeProvider, claims):
    provider.claims = claims
    r = _login(app_client, provider)
    assert "auth_error=failed" in r.headers["location"]
    assert app_client.get("/api/decks").status_code == 401


def test_denied_by_authentik(app_client: TestClient, provider: FakeProvider):
    app_client.get("/api/auth/login", follow_redirects=False)
    r = app_client.get("/api/auth/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert r.headers["location"] == "/?auth_error=denied"


@pytest.mark.parametrize(
    "bad", ["//evil.test/x", "https://evil.test", "/api/decks", "/\\evil.test", "x", "/" + "a" * 600]
)
def test_next_stays_in_the_app(app_client: TestClient, provider: FakeProvider, bad):
    r = _login(app_client, provider, next_path=bad)
    assert r.headers["location"] == "/"


def test_allowed_groups(seeded, provider):
    settings = _settings(seeded, anki_oidc_allowed_groups="authentik Admins")
    with TestClient(create_app(settings), base_url="https://anki.test") as c:
        r = _login(c, provider)
        assert "auth_error=forbidden" in r.headers["location"]
        assert c.get("/api/decks").status_code == 401
        provider.claims = {"groups": ["authentik Admins"]}
        _login(c, provider)
        assert c.get("/api/decks").status_code == 200


def test_allowed_users(seeded, provider):
    settings = _settings(seeded, anki_oidc_allowed_users="JOE")
    with TestClient(create_app(settings), base_url="https://anki.test") as c:
        _login(c, provider)
        assert c.get("/api/decks").status_code == 200


def test_cross_origin_writes_rejected(app_client: TestClient, provider: FakeProvider):
    _login(app_client, provider)
    # da un altro sottodominio dello stesso sito: il cookie Lax passerebbe
    r = app_client.post("/api/sync/logout", headers={"Sec-Fetch-Site": "same-site"})
    assert r.status_code == 403
    r = app_client.post("/api/sync/logout", headers={"Origin": "https://evil.jshep.xyz"})
    assert r.status_code == 403
    assert app_client.post("/api/sync/logout", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 204
    assert app_client.post("/api/sync/logout", headers={"Origin": "https://anki.test"}).status_code == 204
    # le letture no: <img> e navigazioni non sono un rischio
    assert app_client.get("/api/decks", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_tampered_session(app_client: TestClient, provider: FakeProvider):
    _login(app_client, provider)
    value = app_client.cookies["anki_studio_session"]
    body, mac = value.split(".")
    forged = _b64({"sub": "altro", "name": "x", "exp": int(time.time()) + 999})
    app_client.cookies.set("anki_studio_session", f"{forged}.{mac}", domain="anki.test")
    assert app_client.get("/api/decks").status_code == 401


def test_session_survives_restart(seeded, provider):
    """La chiave dei cookie deriva dal client secret: un riavvio non fa rifare il login."""
    settings = _settings(seeded)
    with TestClient(create_app(settings), base_url="https://anki.test") as c:
        _login(c, provider)
        cookie = c.cookies["anki_studio_session"]
    with TestClient(create_app(settings), base_url="https://anki.test") as c:
        c.cookies.set("anki_studio_session", cookie, domain="anki.test")
        assert c.get("/api/decks").status_code == 200


def test_logout(app_client: TestClient, provider: FakeProvider):
    _login(app_client, provider)
    r = app_client.post("/api/auth/logout")
    assert r.json() == {"logout_url": f"{ISSUER}end-session/"}
    assert app_client.get("/api/decks").status_code == 401


def test_bearer_without_configured_token(app_client: TestClient):
    # la PWA vecchia in cache manda ancora il token: 401, ma l'IP non viene bloccato
    for _ in range(30):
        r = app_client.get("/api/decks", headers={"Authorization": "Bearer token-della-pwa-vecchia"})
        assert r.status_code == 401
    assert app_client.get("/api/auth/me").status_code == 401  # non 429


def test_unconfigured_login(seeded):
    settings, _ = seeded
    with TestClient(create_app(settings), base_url="https://anki.test") as c:
        r = c.get("/api/auth/login", follow_redirects=False)
        assert r.headers["location"] == "/?auth_error=unconfigured"


def test_dev_login(seeded):
    settings = seeded[0].model_copy(update={"anki_dev_login": True, "anki_api_token": None})
    with TestClient(create_app(settings), base_url="https://anki.test") as c:
        r = c.get("/api/auth/login", params={"next": "/#/settings"}, follow_redirects=False)
        assert r.headers["location"] == "/#/settings"
        assert c.get("/api/auth/me").json()["username"] is None
        assert c.get("/api/decks").status_code == 200


def test_dev_login_refused_with_pwa(seeded, tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<div id=root></div>")
    settings = seeded[0].model_copy(update={"anki_dev_login": True, "anki_web_dir": tmp_path / "web"})
    with pytest.raises(RuntimeError):
        create_app(settings)


def test_oidc_settings(tmp_path, monkeypatch):
    for k in ("ANKI_API_TOKEN", "ANKI_API_TOKEN_FILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANKI_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("ANKI_OIDC_CLIENT_ID", CLIENT_ID)
    with pytest.raises(ValueError, match="OIDC incompleto"):
        Settings(_env_file=None)
    f = tmp_path / "secret"
    f.write_text(SECRET + "\n")
    monkeypatch.setenv("ANKI_OIDC_CLIENT_SECRET_FILE", str(f))
    monkeypatch.setenv("ANKI_PUBLIC_URL", "https://anki.test/")
    s = Settings(_env_file=None)
    assert s.anki_oidc_client_secret == SECRET
    assert s.redirect_uri == "https://anki.test/api/auth/callback"
    assert s.public_origin == "https://anki.test"
    assert s.anki_api_token is None
