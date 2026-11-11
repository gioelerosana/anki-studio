"""La PWA servita da FastAPI nell'immagine unica (app/web.py): cache, fallback SPA,
header di sicurezza e confine con /api, cioè quello che prima faceva nginx."""

import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.config import Settings
from app.main import create_app

from .conftest import TOKEN

INLINE = "\n      window.__boot = 1;\n    "
INDEX = f"""<!doctype html>
<html><head>
<script>{INLINE}</script>
<script type="module" crossorigin src="/assets/index-abc123.js"></script>
</head><body><div id="root"></div></body></html>"""


@pytest.fixture
def web_dir(tmp_path):
    d = tmp_path / "web"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(INDEX)
    (d / "sw.js").write_text("self.addEventListener('install', () => {});")
    (d / "manifest.webmanifest").write_text('{"name": "Anki Studio"}')
    (d / "icon-256.png").write_bytes(b"\x89PNG fake")
    (d / "assets" / "index-abc123.js").write_text("console.log('app');")
    (d / "assets" / "index-abc123.css").write_text("body{}")
    # un file fuori dalla build: non deve essere raggiungibile
    (tmp_path / "segreto.txt").write_text("non leggermi")
    return d


@pytest.fixture
def web_client(seeded, web_dir):
    settings, did = seeded
    settings = settings.model_copy(
        update={
            "anki_web_dir": web_dir,
            "anki_studio_version": "1.2.3",
            "anki_studio_revision": "abc1234",
        }
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_index_no_cache_and_csp(web_client: TestClient):
    r = web_client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    csp = r.headers["content-security-policy"]
    digest = base64.b64encode(hashlib.sha256(INLINE.encode()).digest()).decode()
    assert f"script-src 'self' 'sha256-{digest}'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    # niente HSTS su http: lo mette solo una richiesta arrivata in HTTPS
    assert "strict-transport-security" not in r.headers


def test_spa_fallback(web_client: TestClient):
    for path in ("/decks/42", "/impostazioni", "/una/rotta/profonda", "/docs", "/openapi.json"):
        r = web_client.get(path)
        assert r.status_code == 200, path
        assert r.text == INDEX, path
        assert r.headers["cache-control"] == "no-cache"
    # HEAD come GET, senza body
    r = web_client.head("/decks/42")
    assert r.status_code == 200 and r.content == b""


def test_assets_immutable(web_client: TestClient):
    r = web_client.get("/assets/index-abc123.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "content-security-policy" not in r.headers
    assert web_client.get("/assets/index-abc123.css").headers["cache-control"].endswith("immutable")


def test_missing_asset_is_404_not_index(web_client: TestClient):
    # un chunk vecchio dopo un aggiornamento: index.html al suo posto finirebbe in cache
    # nel service worker come se fosse JavaScript
    for path in ("/assets/index-vecchio.js", "/assets", "/assets/"):
        r = web_client.get(path)
        assert r.status_code == 404, path
        assert r.text != INDEX


def test_service_worker_and_manifest_no_cache(web_client: TestClient):
    r = web_client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers["cache-control"] == "no-cache"
    r = web_client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert web_client.get("/icon-256.png").headers["cache-control"] == "no-cache"


def test_etag_revalidation(web_client: TestClient):
    r = web_client.get("/sw.js")
    etag = r.headers["etag"]
    r2 = web_client.get("/sw.js", headers={"If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.headers["cache-control"] == "no-cache"


def test_api_never_falls_back_to_pwa(web_client: TestClient):
    for path in ("/api/nonesiste", "/api/decks/1/nonesiste", "/api"):
        r = web_client.get(path, headers={"Authorization": f"Bearer {TOKEN}"})
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/json"), path
        assert r.headers["cache-control"] == "no-store", path
    # metodo sbagliato su una rotta vera: resta 405, non diventa la PWA
    r = web_client.put("/api/decks", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 405
    # le rotte protette chiedono ancora il token
    assert web_client.get("/api/decks").status_code == 401


MCP_ISSUER = "https://auth.example.test/application/o/anki-studio-mcp/"


def web_client_with(seeded, web_dir, **overrides):
    settings, _ = seeded
    settings = settings.model_copy(update={"anki_web_dir": web_dir, **overrides})
    return TestClient(create_app(settings))


def test_mcp_and_well_known_never_fall_back_to_pwa(seeded, web_dir):
    """Un 200 HTML su /mcp o sui metadati OAuth farebbe ignorare a Claude il WWW-Authenticate:
    questi percorsi sono del backend, mai della PWA (come /api)."""
    oauth = {
        "anki_public_url": "https://anki.test",
        "anki_mcp_oidc_issuer": MCP_ISSUER,
        "anki_mcp_oidc_client_id": "anki-mcp",
    }
    with web_client_with(seeded, web_dir, **oauth) as c:
        for path in ("/mcp", "/mcp/"):
            r = c.get(path, follow_redirects=False)
            assert r.status_code == 401, path
            assert r.text != INDEX and "resource_metadata" in r.headers["www-authenticate"]
            r = c.post(path, json={}, follow_redirects=False)
            assert r.status_code == 401, path
        for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
            r = c.get(path)
            assert r.status_code == 200 and r.json()["resource"] == "https://anki.test/mcp", path
        # il resto sotto questi prefissi è un 404 vero, non la PWA
        for path in ("/mcp/altro", "/.well-known/oauth-authorization-server", "/.well-known/nonesiste"):
            r = c.get(path)
            assert r.status_code == 404 and r.text != INDEX, path
        # e le rotte vicine restano della PWA
        assert c.get("/mcpx").text == INDEX and c.get("/well-known/x").text == INDEX


def test_mcp_paths_are_404_not_pwa_when_disabled_or_without_oauth(seeded, web_dir):
    with web_client_with(seeded, web_dir, anki_mcp_enabled=False) as c:
        for path in ("/mcp", "/mcp/", "/.well-known/oauth-protected-resource"):
            r = c.get(path)
            assert r.status_code == 404 and r.text != INDEX, path
    with web_client_with(seeded, web_dir) as c:  # MCP acceso ma senza OAuth
        assert c.get("/.well-known/oauth-protected-resource").status_code == 404
        assert c.get("/.well-known/oauth-protected-resource/mcp").text != INDEX
        r = c.post("/mcp", json={})
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_api_headers_unchanged(web_client: TestClient):
    r = web_client.get("/api/decks", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-security-policy"].startswith("default-src 'none'")


def test_static_rejects_writes(web_client: TestClient):
    assert web_client.post("/").status_code == 405
    assert web_client.delete("/sw.js").status_code == 405


def test_no_path_traversal(web_client: TestClient):
    for path in ("/../segreto.txt", "/%2e%2e/segreto.txt", "/assets/..%2f..%2fsegreto.txt"):
        r = web_client.get(path)
        assert "non leggermi" not in r.text, path


def test_hsts_on_https(seeded, web_dir):
    settings, _ = seeded
    settings = settings.model_copy(update={"anki_web_dir": web_dir})
    with TestClient(create_app(settings), base_url="https://testserver") as c:
        for path in ("/", "/assets/index-abc123.js", "/api/health"):
            assert "max-age=" in c.get(path).headers["strict-transport-security"], path


def test_health_reports_version(web_client: TestClient):
    body = web_client.get("/api/health").json()
    assert body["ok"] is True
    assert body["version"] == "1.2.3"
    assert body["revision"] == "abc1234"


def test_docs_only_without_pwa(client: TestClient):
    # senza ANKI_WEB_DIR (sviluppo) la documentazione interattiva c'è ancora
    assert client.get("/openapi.json").status_code == 200
    body = client.get("/api/health").json()
    assert body["version"] == "dev" and body["revision"] is None


def test_without_pwa_root_is_404(client: TestClient):
    assert client.get("/").status_code == 404


def test_missing_build_fails_loudly(seeded, tmp_path):
    settings, _ = seeded
    settings = settings.model_copy(update={"anki_web_dir": tmp_path / "vuota"})
    with pytest.raises(RuntimeError):
        create_app(settings)


def test_body_limit(seeded, monkeypatch):
    monkeypatch.setattr(app_main, "MAX_BODY_BYTES", 1024)
    settings, did = seeded
    with TestClient(create_app(settings)) as c:
        # anche senza token: il body enorme viene rifiutato prima di essere letto tutto
        r = c.post("/api/notes", content=b"x" * 4096, headers={"Content-Type": "application/json"})
        assert r.status_code == 413
        ok = c.post(
            "/api/sync/login",
            json={"username": "a", "password": "b"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert ok.status_code != 413


def test_token_from_file(tmp_path, monkeypatch):
    f = tmp_path / "anki_api_token"
    f.write_text("token-dal-file-abcdefghij\n")
    monkeypatch.delenv("ANKI_API_TOKEN", raising=False)
    monkeypatch.setenv("ANKI_API_TOKEN_FILE", str(f))
    assert Settings(_env_file=None).anki_api_token == "token-dal-file-abcdefghij"
    # il file vince sulla variabile in chiaro
    monkeypatch.setenv("ANKI_API_TOKEN", "token-in-chiaro-abcdefghij")
    assert Settings(_env_file=None).anki_api_token == "token-dal-file-abcdefghij"


def test_token_file_missing_does_not_leak(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKI_API_TOKEN", "token-in-chiaro-abcdefghij")
    monkeypatch.setenv("ANKI_API_TOKEN_FILE", str(tmp_path / "manca"))
    with pytest.raises(ValueError) as exc:
        Settings(_env_file=None)
    assert "token-in-chiaro" not in str(exc.value)


def test_short_token_not_in_error(monkeypatch):
    monkeypatch.delenv("ANKI_API_TOKEN_FILE", raising=False)
    monkeypatch.setenv("ANKI_API_TOKEN", "corto-segreto")
    with pytest.raises(ValueError) as exc:
        Settings(_env_file=None)
    assert "corto-segreto" not in str(exc.value)
