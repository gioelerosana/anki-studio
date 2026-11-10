"""Matrice "chi può cosa" (docs/PIANO-HUB.md): token read, token write, sessione, amministratore."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app

from .test_hub import basic, get_note, post_batch


@pytest.fixture
def ids(client):
    note = client.get("/api/search/notes?q=ser").json()["notes"][0]
    return {"note": note["id"], "card": note["card_ids"][0], "deck": client.deck_id}


def allowed_reads(ids):
    return [
        "/api/decks",
        "/api/notetypes",
        "/api/search/notes?q=ser",
        "/api/tags",
        f"/api/notes/{ids['note']}",
        f"/api/cards/{ids['card']}/preview",
        "/api/hub/summary",
        "/api/hub/drafts",
        "/api/sync",
    ]


def forbidden_requests(ids):
    n, c, d = ids["note"], ids["card"], ids["deck"]
    return [
        # letture non elencate: studio (ha effetti), statistiche, media, auth
        ("GET", f"/api/decks/{d}/study", None),
        ("GET", f"/api/decks/{d}/options", None),
        ("GET", "/api/stats", None),
        ("GET", "/api/stats/today", None),
        ("GET", "/api/media/pic.png", None),
        ("GET", "/api/auth/me", None),
        ("GET", "/api/tokens", None),
        # distruttive o riservate all'utente
        ("POST", "/api/hub/drafts/approve", {"note_ids": [n]}),
        ("POST", "/api/hub/drafts/discard", {"note_ids": [n]}),
        ("POST", f"/api/notes/{n}/move", {"deck_id": d}),
        ("DELETE", f"/api/notes/{n}", None),
        ("POST", "/api/notes/tags", {"note_ids": [n], "add": ["x"]}),
        ("POST", "/api/notes", {"deck_id": d, "notetype_id": 1, "fields": {}}),
        ("POST", "/api/tokens", {"name": "altro"}),
        ("PATCH", "/api/tokens/abc", {"review": False}),
        ("DELETE", "/api/tokens/abc", None),
        ("POST", "/api/sync/login", {"username": "a", "password": "b"}),
        ("POST", "/api/sync/logout", None),
        ("POST", "/api/sync/full", {"direction": "upload"}),
        # studio e carte
        ("POST", f"/api/decks/{d}/study/answer", {"card_id": c, "rating": 3, "time_taken_ms": 1}),
        ("POST", f"/api/decks/{d}/study/undo", None),
        ("POST", f"/api/decks/{d}/extend-limits", {"new": 1}),
        ("POST", f"/api/cards/{c}/suspend", None),
        ("POST", f"/api/cards/{c}/bury", None),
        ("POST", f"/api/cards/{c}/flag", {"flag": 1}),
        ("POST", f"/api/cards/{c}/type-answer", {"typed": "x"}),
    ]


WRITE_ONLY = [
    ("POST", "/api/hub/notes/batch", {"notes": [basic("zz")]}),
    ("POST", "/api/hub/decks", {"name": "Nuovo"}),
    ("POST", "/api/sync", None),
    ("PATCH", "/api/notes/{note}", {"fields": {"Back": "x"}}),
]


def call(client, method, path, body, headers):
    return client.request(method, path, json=body, headers=headers)


def test_read_token_reads_and_nothing_else(client, make_token, ids):
    headers, _ = make_token("lettore", scope="read")
    for path in allowed_reads(ids):
        assert client.get(path, headers=headers).status_code == 200, path
    for method, path, body in [*forbidden_requests(ids), *WRITE_ONLY]:
        r = call(client, method, path.format(**ids), body, headers)
        assert r.status_code == 403, (method, path, r.status_code)


def test_write_token_writes_only_what_the_plan_allows(client, make_token, ids):
    headers, _ = make_token("scrittore", scope="write")
    for path in allowed_reads(ids):
        assert client.get(path, headers=headers).status_code == 200, path
    for method, path, body in forbidden_requests(ids):
        r = call(client, method, path, body, headers)
        assert r.status_code == 403, (method, path, r.status_code)
    # il 403 arriva prima di qualsiasi effetto: la nota c'è ancora, nessun token creato
    assert client.get(f"/api/notes/{ids['note']}").status_code == 200
    assert [t["name"] for t in client.get("/api/tokens").json()] == ["scrittore"]

    assert call(client, "POST", "/api/hub/notes/batch", {"notes": [basic("zz")]}, headers).status_code == 200
    assert call(client, "POST", "/api/hub/decks", {"name": "Nuovo"}, headers).status_code == 200
    # senza AnkiWeb collegato la sync dice 401, ma la rotta è permessa (non 403)
    assert call(client, "POST", "/api/sync", None, headers).status_code != 403


def test_write_token_patches_only_its_own_notes(client, make_token, ids):
    mine_h, _ = make_token("mio", scope="write")
    other_h, _ = make_token("altro", scope="write")
    mine = post_batch(client, [basic("m1")], headers=mine_h)["results"][0]["note_id"]
    theirs = post_batch(client, [basic("t1")], headers=other_h)["results"][0]["note_id"]
    plain = ids["note"]  # creata dal seed, senza provenienza

    ok = client.patch(f"/api/notes/{mine}", json={"fields": {"Back": "nuovo"}}, headers=mine_h)
    assert ok.status_code == 200 and ok.json()["fields"]["Back"] == "nuovo"
    for nid in (theirs, plain):
        r = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "hack"}}, headers=mine_h)
        assert r.status_code == 403
        assert get_note(client, nid)["fields"]["Back"] != "hack"
    assert client.patch("/api/notes/1", json={"fields": {}}, headers=mine_h).status_code == 404


def test_token_cannot_change_reserved_tags_of_its_notes(client, make_token):
    headers, _ = make_token("claude", scope="write", review=True)
    nid = post_batch(client, [basic("b", external_id="e")], headers=headers)["results"][0]["note_id"]
    r = client.patch(
        f"/api/notes/{nid}",
        json={"tags": ["utile", "agent::altro", "hub::approvata", "ext::altro"]},
        headers=headers,
    )
    assert r.status_code == 200
    assert set(r.json()["tags"]) == {"utile", "agent::claude", "hub::bozza", "ext::e"}
    # nemmeno svuotando i tag si toglie lo stato di bozza o la provenienza
    r = client.patch(f"/api/notes/{nid}", json={"tags": []}, headers=headers)
    assert set(r.json()["tags"]) == {"agent::claude", "hub::bozza", "ext::e"}
    # la sessione/amministratore invece è libera
    r = client.patch(f"/api/notes/{nid}", json={"tags": ["solo"]})
    assert r.json()["tags"] == ["solo"]


def test_admin_token_can_do_everything(client, ids):
    for method, path, body in forbidden_requests(ids)[:4]:
        assert client.request(method, path, json=body).status_code != 403
    assert client.get("/api/tokens").status_code == 200


def test_scoped_tokens_stay_out_of_the_remote_control(client, make_token):
    headers, _ = make_token("claude", scope="write")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/remote?role=remote", headers=headers):
            pass


# ---- sessione --------------------------------------------------------------------------


@pytest.fixture
def session_client(seeded):
    settings, did = seeded
    settings = settings.model_copy(update={"anki_dev_login": True, "anki_api_token": None})
    with TestClient(create_app(settings), base_url="https://anki.test") as c:
        c.get("/api/auth/login", follow_redirects=False)
        c.deck_id = did
        yield c


def test_session_can_do_everything_and_creates_plain_notes(session_client):
    c = session_client
    out = post_batch(c, [basic("sessione")])
    assert out["draft"] is False
    nid = out["results"][0]["note_id"]
    assert not any(t.startswith("agent::") for t in get_note(c, nid)["tags"])
    token = c.post("/api/tokens", json={"name": "claude"})
    assert token.status_code == 201
    assert c.delete(f"/api/notes/{nid}").status_code == 204
    assert c.get("/api/auth/me").status_code == 200


def test_session_writes_are_csrf_protected(session_client):
    c = session_client
    body = {"notes": [basic("csrf")]}
    r = c.post("/api/hub/notes/batch", json=body, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = c.post("/api/tokens", json={"name": "x"}, headers={"Origin": "https://evil.test"})
    assert r.status_code == 403
    assert c.get("/api/tokens").json() == []
    r = c.post("/api/hub/notes/batch", json=body, headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


def test_without_credentials_everything_is_401(client):
    for method, path in [
        ("POST", "/api/hub/notes/batch"),
        ("GET", "/api/hub/summary"),
        ("GET", "/api/tokens"),
        ("DELETE", "/api/notes/1"),
        ("GET", "/api/cards/1/preview"),
    ]:
        assert client.request(method, path, headers={"Authorization": ""}).status_code == 401
