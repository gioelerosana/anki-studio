"""Token per gli agenti: hash a riposo, mostrati una volta, revoca, last_used_at, rate limit."""

import json
import logging
import os
import stat
import time

import pytest
from fastapi.testclient import TestClient

from app.logging_setup import redact
from app.main import create_app
from app.tokens import TokenStore

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


def test_unreadable_tokens_file_is_set_aside_not_overwritten(seeded, caplog):
    settings, _ = seeded
    path = settings.anki_data_dir / "tokens.json"
    path.write_text("{non json")
    caplog.set_level(logging.WARNING)
    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        assert c.get("/api/tokens").json() == []
        # il file rovinato non rompe la creazione di un token nuovo...
        assert c.post("/api/tokens", json={"name": "claude"}).status_code == 201
    # ...ma non va perso: resta in un backup col timestamp, riservato come l'originale
    backups = list(settings.anki_data_dir.glob("tokens.json.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "{non json"
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    assert json.loads(path.read_text())["tokens"][0]["name"] == "claude"
    # il warning dice cosa è successo, senza contenuti del file
    assert "tokens.json" in caplog.text and "non json" not in caplog.text


@pytest.mark.parametrize(
    "content",
    [
        '{"tokens": [{"id": "a"}]}',  # token senza i campi obbligatori
        '{"tokens": "no"}',
        "[]",
        '{"tokens": [], "revoked": "no"}',
        "",
    ],
)
def test_tokens_file_with_the_wrong_shape_is_set_aside_too(seeded, content):
    settings, _ = seeded
    path = settings.anki_data_dir / "tokens.json"
    path.write_text(content)
    TokenStore(path).create("claude", "write", True)
    assert [p.read_text() for p in settings.anki_data_dir.glob("tokens.json.bak-*")] == [content]


def test_unknown_fields_in_tokens_file_do_not_wipe_the_tokens(tmp_path):
    """Un file scritto da una versione più nuova (un campo in più) e poi un downgrade: i token
    restano validi."""
    path = tmp_path / "tokens.json"
    token, plain = TokenStore(path).create("claude", "write", True)
    raw = json.loads(path.read_text())
    raw["tokens"][0]["expires_at"] = 123
    raw["futuro"] = True
    path.write_text(json.dumps(raw))
    store = TokenStore(path)
    assert [t.id for t in store.all()] == [token.id]
    assert store.verify(plain) is not None
    assert not list(tmp_path.glob("tokens.json.bak-*"))


def test_a_missing_tokens_file_is_not_an_error(tmp_path):
    store = TokenStore(tmp_path / "tokens.json")
    assert store.all() == []
    assert not list(tmp_path.glob("*.bak-*"))


def test_unmovable_unreadable_file_is_never_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "tokens.json"
    path.write_text("{non json")

    real = os.replace

    def refuse_to_move_it(src, dst, *a, **k):
        if str(src) == str(path):  # il backup non riesce; la scrittura del file nuovo sì
            raise OSError("sola lettura")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", refuse_to_move_it)
    store = TokenStore(path)
    with pytest.raises(OSError):
        store.create("claude", "write", True)
    assert path.read_text() == "{non json"


# ---- un token revocato non blocca nessun altro ---------------------------------------------


@pytest.fixture
def owner(seeded):
    """La PWA col cookie di sessione (login di sviluppo), con 3 Bearer sbagliati di tolleranza."""
    settings, did = seeded
    settings = settings.model_copy(
        update={"anki_api_token": None, "anki_dev_login": True, "anki_token_max_failures": 3}
    )
    with TestClient(create_app(settings), base_url="https://anki.test") as c:
        c.get("/api/auth/login", follow_redirects=False)
        c.deck_id = did
        yield c


def create_token(owner, name="hermes"):
    return owner.post("/api/tokens", json={"name": name}).json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_a_revoked_token_retrying_in_a_loop_blocks_nobody(owner):
    old = create_token(owner, "hermes")
    live = create_token(owner, "altro")["token"]
    assert owner.delete(f"/api/tokens/{old['id']}").status_code == 204
    for _ in range(20):  # molto oltre il limite di 3
        assert owner.get("/api/decks", headers=bearer(old["token"])).status_code == 401
    # né il proprietario (sessione), né un altro token dello stesso IP sono bloccati
    assert owner.get("/api/decks").status_code == 200
    assert owner.get("/api/decks", headers=bearer(live)).status_code == 200


def test_a_revoked_token_on_mcp_blocks_nobody(owner):
    from .test_mcp import headers_for

    old = create_token(owner, "hermes")
    owner.delete(f"/api/tokens/{old['id']}")
    for _ in range(20):
        r = owner.post("/mcp", json={}, headers=headers_for(old["token"]))
        assert r.status_code == 401
    assert owner.get("/api/decks").status_code == 200
    assert owner.get("/api/decks", headers=bearer(create_token(owner, "nuovo")["token"])).status_code == 200


def test_guessing_tokens_still_counts_but_never_locks_out_the_session(owner):
    good = create_token(owner)["token"]
    for _ in range(3):
        assert owner.get("/api/decks", headers=bearer("ask_" + "x" * 43)).status_code == 401
    # chi prova un Bearer è bloccato, anche con quello giusto (non si deve capire quando si indovina)...
    r = owner.get("/api/decks", headers=bearer(good))
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert owner.post("/mcp", json={}, headers=bearer(good)).status_code == 429
    # ...ma la richiesta col cookie di sessione, senza Bearer, passa. Anche per scrivere.
    assert owner.get("/api/decks").status_code == 200
    assert owner.post("/api/hub/decks", json={"name": "Nuovo"}).status_code == 200
    assert owner.get("/api/auth/me").status_code == 200


def test_a_token_that_never_existed_counts_even_if_it_looks_like_a_revoked_one(owner):
    # un hash revocato è di un token vero: uno inventato non lo è
    old = create_token(owner)
    owner.delete(f"/api/tokens/{old['id']}")
    for _ in range(3):
        assert owner.get("/api/decks", headers=bearer(old["token"][:-1] + "A")).status_code == 401
    assert owner.get("/api/decks", headers=bearer(old["token"])).status_code == 429


def test_revoked_hashes_survive_a_restart_and_never_hold_the_plain_token(seeded):
    settings, _ = seeded
    store = TokenStore(settings.anki_data_dir / "tokens.json")
    token, plain = store.create("claude", "write", False)
    store.revoke(token.id)
    again = TokenStore(settings.anki_data_dir / "tokens.json")
    assert again.is_revoked(plain) and not again.is_revoked("ask_altro")
    assert plain not in (settings.anki_data_dir / "tokens.json").read_text()


def test_failed_oidc_logins_do_not_lock_out_the_session(owner):
    """Il limite del login OIDC (`token_limiter`) è un altro e non tocca le richieste normali."""
    for _ in range(5):
        owner.app.state.token_limiter.hit("testclient")
    assert owner.get("/api/decks").status_code == 200
    assert owner.get("/api/decks", headers=bearer(create_token(owner)["token"])).status_code == 200


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
