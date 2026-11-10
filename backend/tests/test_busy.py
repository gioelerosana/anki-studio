"""Collezione occupata (di solito da una sync): le rotte e gli strumenti MCP rispondono 503 /
«riprova» invece di restare appesi, e non scrivono niente."""

import threading
from contextlib import contextmanager

import pytest

from .conftest import note_count
from .test_hub import basic, post_batch
from .test_mcp import PNG_B64, call, mcp_client, note_args, text_of, tokens  # noqa: F401


@contextmanager
def collection_held(app):
    """Tiene il lock della collezione da un altro thread, come farebbe una sync lunga."""
    manager = app.state.manager
    manager.busy_timeout = 0.05
    release, held = threading.Event(), threading.Event()

    def hold():
        with manager.use():
            held.set()
            release.wait(10)

    thread = threading.Thread(target=hold)
    thread.start()
    assert held.wait(5)
    try:
        yield
    finally:
        release.set()
        thread.join()


@pytest.fixture
def ids(client, make_token):
    headers, _ = make_token("claude", review=True)
    nid = post_batch(client, [basic("bozza", external_id="b")], headers=headers)["results"][0]["note_id"]
    note = client.get("/api/search/notes?q=ser").json()["notes"][0]
    return {"draft": nid, "card": note["card_ids"][0], "note": note["id"], "deck": client.deck_id}


def routes(ids):
    d, n, c = ids["draft"], ids["note"], ids["card"]
    return [
        ("POST", "/api/hub/notes/batch", {"notes": [basic("nuova")]}),
        ("POST", "/api/hub/notes/batch", {"notes": [basic("nuova")], "dry_run": True}),
        ("POST", "/api/hub/decks", {"name": "Nuovo"}),
        ("GET", "/api/hub/summary", None),
        ("GET", "/api/hub/drafts", None),
        ("POST", "/api/hub/drafts/approve", {"note_ids": [d]}),
        ("POST", "/api/hub/drafts/discard", {"note_ids": [d]}),
        ("GET", f"/api/cards/{c}/preview", None),
        ("POST", f"/api/notes/{n}/move", {"deck_id": ids["deck"]}),
        ("DELETE", f"/api/notes/{n}", None),
        ("POST", "/api/notes/tags", {"note_ids": [n], "add": ["x"]}),
        ("PATCH", f"/api/notes/{n}", {"fields": {"Back": "x"}}),
        ("POST", "/api/media", {"filename": "a.png", "data_base64": PNG_B64}),
    ]


def test_new_routes_answer_503_when_the_collection_is_busy(client, ids):
    before = note_count(client)
    with collection_held(client.app):
        for method, path, body in routes(ids):
            r = client.request(method, path, json=body)
            assert r.status_code == 503, (method, path, r.status_code)
            assert r.headers["retry-after"] == "5" and "riprova" in r.json()["detail"], (method, path)
    # niente è stato scritto, e appena si libera tutto funziona
    assert note_count(client) == before
    assert client.get("/api/hub/summary").json() == {"drafts": 1}
    assert client.get(f"/api/notes/{ids['note']}").json()["fields"]["Back"] != "x"


def test_mcp_tools_say_the_collection_is_busy(mcp_client, tokens):  # noqa: F811
    token = tokens("claude")
    nid = call(mcp_client, "add_notes", {"notes": [note_args("m")]}, token=token)["structuredContent"]["results"][0]["note_id"]
    calls = [
        ("list_decks", {}),
        ("list_notetypes", {}),
        ("search_notes", {"query": "ser"}),
        ("get_note", {"note_id": nid}),
        ("add_notes", {"notes": [note_args("busy")]}),
        ("update_note", {"note_id": nid, "fields": {"Back": "x"}}),
        ("create_deck", {"name": "Occupato"}),
        ("add_media", {"filename": "a.png", "data_base64": PNG_B64}),
    ]
    with collection_held(mcp_client.app):
        for name, args in calls:
            r = call(mcp_client, name, args, token=token)
            assert r["isError"] and "occupata" in text_of(r) and "riprova" in text_of(r), name
    # niente è stato scritto
    assert note_count(mcp_client) == 4
    assert not call(mcp_client, "get_note", {"note_id": nid}, token=token)["isError"]
    assert call(mcp_client, "get_note", {"note_id": nid}, token=token)["structuredContent"]["fields"]["Back"] == "r"
