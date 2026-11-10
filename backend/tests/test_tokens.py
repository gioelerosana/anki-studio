"""Token per gli agenti: hash a riposo, mostrati una volta, revoca, last_used_at, rate limit."""

import json
import logging
import stat
import time

from fastapi.testclient import TestClient

from app.logging_setup import redact
from app.main import create_app

from .conftest import TOKEN


def test_create_shows_plain_token_once_and_stores_only_the_hash(client, seeded, make_token):
    settings, _ = seeded
    headers, created = make_token("Hermes Agent", scope="write", review=True)
    plain = created["token"]
    assert plain.startswith("ask_") and len(plain) >= 40
    assert created["name"] == "Hermes Agent" and created["scope"] == "write" and created["review"]
    assert created["last_used_at"] is None and created["created_at"] > 0

    path = settings.anki_data_dir / "tokens.json"
    raw = path.read_text()
    assert plain not in raw and "ask_" not in raw
    stored = json.loads(raw)["tokens"][0]
    import hashlib

    assert stored["hash"] == hashlib.sha256(plain.encode()).hexdigest()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not path.with_suffix(".tmp").exists()

    # l'elenco non rivela più il token in chiaro né l'hash
    listing = client.get("/api/tokens")
    assert plain not in listing.text and "hash" not in listing.text
    assert [t["name"] for t in listing.json()] == ["Hermes Agent"]
    assert "token" not in listing.json()[0]


def test_plain_token_never_in_logs(client, make_token, caplog):
    caplog.set_level(logging.DEBUG)
    headers, created = make_token("claude")
    plain = created["token"]
    client.get("/api/decks", headers=headers)
    client.post("/api/hub/drafts/approve", json={"note_ids": [1]}, headers=headers)  # 403, logga
    client.get("/api/decks", headers={"Authorization": "Bearer ask_sbagliato"})
    assert plain not in caplog.text
    # e il filtro dei log lo oscura comunque, se finisse in un messaggio o in un traceback
    assert redact(f"Authorization: Bearer {plain}") == "Authorization: Bearer ***"


def test_token_works_until_revoked(client, make_token):
    headers, created = make_token("claude")
    assert client.get("/api/decks", headers=headers).status_code == 200
    assert client.delete(f"/api/tokens/{created['id']}").status_code == 204
    assert client.get("/api/decks", headers=headers).status_code == 401
    assert client.delete(f"/api/tokens/{created['id']}").status_code == 404
    assert client.get("/api/tokens").json() == []


def test_tokens_survive_restart(seeded):
    settings, _ = seeded
    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        plain = c.post("/api/tokens", json={"name": "claude"}).json()["token"]
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/decks", headers={"Authorization": f"Bearer {plain}"}).status_code == 200


def test_last_used_at_is_updated(client, make_token):
    headers, created = make_token("claude")
    assert client.get("/api/tokens").json()[0]["last_used_at"] is None
    before = int(time.time())
    client.get("/api/decks", headers=headers)
    used = client.get("/api/tokens").json()[0]["last_used_at"]
    assert used is not None and before <= used <= int(time.time())


def test_last_used_at_is_persisted_sparingly(client, seeded, make_token):
    settings, _ = seeded
    headers, _ = make_token("claude")
    path = settings.anki_data_dir / "tokens.json"
    client.get("/api/decks", headers=headers)
    assert json.loads(path.read_text())["tokens"][0]["last_used_at"] is not None
    mtime = path.stat().st_mtime_ns
    for _ in range(5):
        client.get("/api/decks", headers=headers)
    assert path.stat().st_mtime_ns == mtime  # niente riscritture a ogni richiesta


def test_update_scope_and_review(client, make_token):
    headers, created = make_token("claude", scope="write", review=True)
    r = client.patch(f"/api/tokens/{created['id']}", json={"scope": "read", "review": False})
    assert r.status_code == 200 and r.json()["scope"] == "read" and r.json()["review"] is False
    # il nuovo scope vale subito
    assert client.post(
        "/api/hub/decks", json={"name": "X"}, headers=headers
    ).status_code == 403
    assert client.patch("/api/tokens/nope", json={"review": True}).status_code == 404


def test_names_are_unique_by_slug(client, make_token):
    make_token("Hermes Agent")
    r = client.post("/api/tokens", json={"name": "hermes-agent"})
    assert r.status_code == 409
    assert client.post("/api/tokens", json={"name": "  "}).status_code == 422
    assert client.post("/api/tokens", json={"name": "!!!"}).status_code == 422
    assert client.post("/api/tokens", json={"name": "Perché"}).status_code == 201


def test_wrong_tokens_are_rate_limited(seeded):
    settings, _ = seeded
    settings = settings.model_copy(update={"anki_token_max_failures": 3})
    with TestClient(create_app(settings)) as c:
        good = c.post(
            "/api/tokens", json={"name": "claude"}, headers={"Authorization": f"Bearer {TOKEN}"}
        ).json()["token"]
        for _ in range(3):
            r = c.get("/api/decks", headers={"Authorization": "Bearer ask_" + "x" * 43})
            assert r.status_code == 401
        # stesso limite di ANKI_API_TOKEN: dopo troppi errori anche le credenziali giuste sono bloccate
        r = c.get("/api/decks", headers={"Authorization": f"Bearer {good}"})
        assert r.status_code == 429 and "Retry-After" in r.headers


def test_corrupt_tokens_file_is_ignored(seeded):
    settings, _ = seeded
    (settings.anki_data_dir / "tokens.json").write_text("{non json")
    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        assert c.get("/api/tokens").json() == []
        # il file rovinato non rompe la creazione di un token nuovo
        assert c.post("/api/tokens", json={"name": "claude"}).status_code == 201


def test_tokens_work_without_admin_token(seeded):
    """Senza ANKI_API_TOKEN (come nello stack) i token `ask_` funzionano lo stesso, e un
    Bearer qualsiasi resta 401 senza far bloccare l'IP (la PWA vecchia con il suo token)."""
    settings, _ = seeded
    settings = settings.model_copy(
        update={"anki_api_token": None, "anki_dev_login": True, "anki_token_max_failures": 2}
    )
    with TestClient(create_app(settings), base_url="https://anki.test") as c:
        c.get("/api/auth/login", follow_redirects=False)  # sessione di sviluppo
        plain = c.post("/api/tokens", json={"name": "claude"}).json()["token"]
        c.cookies.clear()
        for _ in range(5):
            assert c.get("/api/decks", headers={"Authorization": "Bearer vecchio-token"}).status_code == 401
        assert c.get("/api/decks", headers={"Authorization": f"Bearer {plain}"}).status_code == 200
