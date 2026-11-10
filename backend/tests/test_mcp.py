"""Server MCP su /mcp: strumenti, permessi (gli stessi della REST), bozze, errori chiari,
sync dopo la scrittura e client dell'SDK su un uvicorn vero (entrambe le versioni del protocollo)."""

import asyncio
import base64
import json
import socket
import threading
import time

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.main import create_app

from .conftest import TOKEN
from .test_hub import basic

EXPECTED_TOOLS = {
    "list_decks",
    "list_notetypes",
    "search_notes",
    "get_note",
    "add_notes",
    "update_note",
    "create_deck",
    "sync_now",
    "sync_status",
    "add_media",
}
READ_ONLY = {"list_decks", "list_notetypes", "search_notes", "get_note", "sync_status"}
PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()

ACCEPT = "application/json, text/event-stream"


def headers_for(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": ACCEPT,
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-11-25",
    }


def rpc(client: TestClient, method: str, params: dict | None = None, *, token: str | None = None, headers=None):
    """Una richiesta JSON-RPC su /mcp. Restituisce la risposta HTTP e il messaggio JSON-RPC."""
    h = headers if headers is not None else headers_for(token or TOKEN)
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, headers=h)
    return r, parse(r)


def parse(r) -> dict | None:
    if r.status_code != 200:
        return None
    if r.headers["content-type"].startswith("text/event-stream"):
        events = [line[6:] for line in r.text.splitlines() if line.startswith("data: ")]
        return json.loads(events[-1])
    return r.json()


def call(client: TestClient, name: str, args: dict | None = None, *, token: str | None = None):
    """Chiama uno strumento: restituisce `result` (content, isError, structuredContent)."""
    r, msg = rpc(client, "tools/call", {"name": name, "arguments": args or {}}, token=token)
    assert r.status_code == 200, r.text
    assert "result" in msg, msg
    return msg["result"]


def text_of(result: dict) -> str:
    return "\n".join(c["text"] for c in result["content"] if c["type"] == "text")


@pytest.fixture
def mcp_client(seeded):
    """Il client di default (amministratore) con una collezione di prova e il server MCP acceso."""
    settings, did = seeded
    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"  # per le chiamate REST di controllo
        c.deck_id = did
        yield c


@pytest.fixture
def tokens(mcp_client):
    """Crea token per gli agenti con l'accesso amministratore."""

    def make(name="claude", scope="write", review=False) -> str:
        r = mcp_client.post(
            "/api/tokens",
            json={"name": name, "scope": scope, "review": review},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert r.status_code == 201, r.text
        return r.json()["token"]

    return make


def note_args(front, back="r", deck="Spagnolo::Verbi", **extra):
    return {"deck": deck, "notetype": "Basic", "fields": {"Front": front, "Back": back}, **extra}


# ---- elenco degli strumenti -----------------------------------------------------------------


def test_initialize_and_tools_list(mcp_client):
    r, msg = rpc(
        mcp_client,
        "initialize",
        {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    )
    assert r.status_code == 200
    info = msg["result"]["serverInfo"]
    assert info["name"] == "Anki Studio"
    # le istruzioni avvertono dei dati non fidati e dicono che le bozze si approvano nella app
    assert "non fidato" in msg["result"]["instructions"] and "BOZZE" in msg["result"]["instructions"]

    r, msg = rpc(mcp_client, "tools/list")
    tools = {t["name"]: t for t in msg["result"]["tools"]}
    # niente strumenti per cancellare, approvare, sync completa o tipi di nota
    assert set(tools) == EXPECTED_TOOLS
    for name, tool in tools.items():
        assert tool["title"] and tool["description"], name
        ann = tool["annotations"]
        assert ann["title"] == tool["title"]
        assert ann["readOnlyHint"] is (name in READ_ONLY), name
        # nessuno strumento cancella: l'unico distruttivo (sovrascrive campi) è update_note
        if name in READ_ONLY:
            assert ann.get("destructiveHint") in (None, False)
        else:
            assert ann["destructiveHint"] is (name == "update_note"), name
    assert tools["sync_now"]["annotations"]["openWorldHint"] is True
    assert tools["add_notes"]["annotations"]["idempotentHint"] is True
    # le descrizioni sono in italiano e i tool che leggono dalla collezione avvertono
    for name in ("search_notes", "get_note"):
        assert "non fidato" in tools[name]["description"], name
    assert "dry_run" in tools["add_notes"]["description"] and "BOZZE" in tools["add_notes"]["description"]
    schema = tools["add_notes"]["inputSchema"]
    assert schema["properties"]["notes"]["maxItems"] == 100 and schema["required"] == ["notes"]
    assert set(schema["properties"]) == {"notes", "dry_run", "create_missing_decks", "draft"}
    assert tools["add_media"]["inputSchema"]["required"] == ["filename", "data_base64"]


# ---- letture ------------------------------------------------------------------------------------


def test_read_tools(mcp_client):
    decks = call(mcp_client, "list_decks")
    assert not decks["isError"]
    names = [d["full_name"] for d in decks["structuredContent"]["result"]]
    assert "Spagnolo" in names

    types = call(mcp_client, "list_notetypes")["structuredContent"]["result"]
    basic_type = next(t for t in types if t["name"] == "Basic")
    assert [f["name"] for f in basic_type["fields"]] == ["Front", "Back"]
    assert any(t["is_cloze"] for t in types)

    found = call(mcp_client, "search_notes", {"query": "ser", "limit": 5})["structuredContent"]
    assert found["total"] == 1 and found["notes"][0]["deck_name"] == "Spagnolo::Verbi"

    note = call(mcp_client, "get_note", {"note_id": found["notes"][0]["id"]})["structuredContent"]
    assert note["notetype_name"] == "Basic" and note["draft"] is False
    assert note["fields"]["Back"].startswith("essere") and note["deck_name"] == "Spagnolo::Verbi"

    status = call(mcp_client, "sync_status")["structuredContent"]
    assert status["logged_in"] is False


def test_read_tool_errors_are_clear(mcp_client):
    bad = call(mcp_client, "search_notes", {"query": 'deck:"'})
    assert bad["isError"] and "Ricerca non valida" in text_of(bad)
    missing = call(mcp_client, "get_note", {"note_id": 1})
    assert missing["isError"] and "Nota non trovata" in text_of(missing)
    # un argomento sbagliato lo rifiuta l'SDK prima dello strumento, con un messaggio leggibile
    wrong = call(mcp_client, "get_note", {"note_id": "abc"})
    assert wrong["isError"] and "note_id" in text_of(wrong)
    unknown = call(mcp_client, "list_decks")  # controllo: il server risponde ancora
    assert not unknown["isError"]


# ---- scritture ----------------------------------------------------------------------------------


def test_add_notes_dry_run_then_real(mcp_client, tokens):
    token = tokens("claude", review=True)
    args = {"notes": [note_args("hablar", "parlare", external_id="v-hablar")], "dry_run": True}
    dry = call(mcp_client, "add_notes", args, token=token)["structuredContent"]
    assert dry["dry_run"] is True and dry["created"] == 1 and dry["draft"] is True
    assert mcp_client.get("/api/hub/summary").json() == {"drafts": 0}

    args["dry_run"] = False
    out = call(mcp_client, "add_notes", args, token=token)["structuredContent"]
    assert out["created"] == 1 and out["results"][0]["status"] == "created"
    nid = out["results"][0]["note_id"]
    note = call(mcp_client, "get_note", {"note_id": nid}, token=token)["structuredContent"]
    # provenienza e bozza, come dalla REST
    assert {"agent::claude", "ext::v-hablar", "hub::bozza"} <= set(note["tags"])
    assert note["draft"] is True
    assert mcp_client.get("/api/hub/summary").json() == {"drafts": 1}
    # rimandare lo stesso external_id non duplica
    again = call(mcp_client, "add_notes", args, token=token)["structuredContent"]
    assert again["unchanged"] == 1 and again["created"] == 0


def test_review_cannot_be_bypassed(mcp_client, tokens):
    review = tokens("revisionato", review=True)
    free = tokens("libero", review=False)
    out = call(mcp_client, "add_notes", {"notes": [note_args("uno")], "draft": False}, token=review)
    assert out["structuredContent"]["draft"] is True
    nid = out["structuredContent"]["results"][0]["note_id"]
    with mcp_client.app.state.manager.use() as col:
        assert all(col.get_card(c).queue == -1 for c in col.get_note(nid).card_ids())
    # senza review (e senza `draft`) le note sono normali; con `draft: true` sono bozze
    plain = call(mcp_client, "add_notes", {"notes": [note_args("due")]}, token=free)["structuredContent"]
    assert plain["draft"] is False
    drafted = call(mcp_client, "add_notes", {"notes": [note_args("tre")], "draft": True}, token=free)
    assert drafted["structuredContent"]["draft"] is True


def test_reserved_tags_are_ignored(mcp_client, tokens):
    token = tokens("claude")
    n = note_args("tag", tags=["utile", "agent::altro", "hub::bozza", "ext::x"])
    out = call(mcp_client, "add_notes", {"notes": [n]}, token=token)["structuredContent"]
    tags = call(mcp_client, "get_note", {"note_id": out["results"][0]["note_id"]}, token=token)["structuredContent"]["tags"]
    assert set(tags) == {"utile", "agent::claude"}


def test_per_note_errors_and_limits(mcp_client, tokens):
    token = tokens("claude")
    out = call(
        mcp_client,
        "add_notes",
        {"notes": [note_args("ok"), {"deck": "Spagnolo::Verbi", "notetype": "Basic", "fields": {"Nope": "x"}}, note_args("nuovo", deck="Assente")]},
        token=token,
    )
    res = out["structuredContent"]
    assert [r["status"] for r in res["results"]] == ["created", "error", "error"]
    assert "Campi inesistenti" in res["results"][1]["error"]
    assert "create_missing_decks" in res["results"][2]["error"]
    # con create_missing_decks il mazzo si crea
    ok = call(mcp_client, "add_notes", {"notes": [note_args("nuovo", deck="Assente::Figlio")], "create_missing_decks": True}, token=token)
    assert ok["structuredContent"]["created"] == 1
    # più di 100 note: la rifiuta lo schema, con un messaggio
    many = call(mcp_client, "add_notes", {"notes": [note_args(f"n{i}") for i in range(101)]}, token=token)
    assert many["isError"] and "100" in text_of(many)
    empty = call(mcp_client, "add_notes", {"notes": []}, token=token)
    assert empty["isError"]


def test_create_deck_is_idempotent(mcp_client, tokens):
    token = tokens("claude")
    first = call(mcp_client, "create_deck", {"name": "Lingue::Francese"}, token=token)["structuredContent"]
    again = call(mcp_client, "create_deck", {"name": "Lingue::Francese"}, token=token)["structuredContent"]
    assert first["created"] is True and again["created"] is False and first["id"] == again["id"]
    bad = call(mcp_client, "create_deck", {"name": "A::::B"}, token=token)
    assert bad["isError"] and "Nome del mazzo non valido" in text_of(bad)


def test_update_note_only_on_own_notes(mcp_client, tokens):
    mine = tokens("mio")
    other = tokens("altro")
    mine_id = call(mcp_client, "add_notes", {"notes": [note_args("m1")]}, token=mine)["structuredContent"]["results"][0]["note_id"]
    theirs_id = call(mcp_client, "add_notes", {"notes": [note_args("t1")]}, token=other)["structuredContent"]["results"][0]["note_id"]
    seed_id = call(mcp_client, "search_notes", {"query": "ser"})["structuredContent"]["notes"][0]["id"]

    ok = call(mcp_client, "update_note", {"note_id": mine_id, "fields": {"Back": "nuovo"}}, token=mine)
    assert not ok["isError"] and ok["structuredContent"]["fields"]["Back"] == "nuovo"
    for nid in (theirs_id, seed_id):
        denied = call(mcp_client, "update_note", {"note_id": nid, "fields": {"Back": "hack"}}, token=mine)
        assert denied["isError"] and "solo le note create da lui" in text_of(denied)
        assert call(mcp_client, "get_note", {"note_id": nid})["structuredContent"]["fields"]["Back"] != "hack"
    missing = call(mcp_client, "update_note", {"note_id": 1, "fields": {"Back": "x"}}, token=mine)
    assert missing["isError"] and "Nota non trovata" in text_of(missing)
    nothing = call(mcp_client, "update_note", {"note_id": mine_id}, token=mine)
    assert nothing["isError"] and "almeno" in text_of(nothing)
    unknown_field = call(mcp_client, "update_note", {"note_id": mine_id, "fields": {"Nope": "x"}}, token=mine)
    assert unknown_field["isError"] and "Campi inesistenti" in text_of(unknown_field)
    # i tag riservati restano com'erano
    tags = call(mcp_client, "update_note", {"note_id": mine_id, "tags": ["x", "agent::altro", "hub::bozza"]}, token=mine)
    assert set(tags["structuredContent"]["tags"]) == {"x", "agent::mio"}


def test_update_note_keeps_draft_state(mcp_client, tokens):
    token = tokens("claude", review=True)
    nid = call(mcp_client, "add_notes", {"notes": [note_args("b")]}, token=token)["structuredContent"]["results"][0]["note_id"]
    out = call(mcp_client, "update_note", {"note_id": nid, "tags": []}, token=token)
    assert "hub::bozza" in out["structuredContent"]["tags"]


def test_admin_can_update_any_note(mcp_client):
    seed_id = call(mcp_client, "search_notes", {"query": "ser"})["structuredContent"]["notes"][0]["id"]
    out = call(mcp_client, "update_note", {"note_id": seed_id, "fields": {"Back": "cambiato"}})
    assert not out["isError"]


def test_add_media(mcp_client, tokens):
    token = tokens("claude")
    ok = call(mcp_client, "add_media", {"filename": "gatto.png", "data_base64": PNG_B64}, token=token)
    assert not ok["isError"] and ok["structuredContent"]["filename"] == "gatto.png"
    bad = call(mcp_client, "add_media", {"filename": "gatto.png", "data_base64": base64.b64encode(b"MZ non png").decode()}, token=token)
    assert bad["isError"] and "non coincidono" in text_of(bad)
    ext = call(mcp_client, "add_media", {"filename": "x.exe", "data_base64": PNG_B64}, token=token)
    assert ext["isError"] and "non ammessa" in text_of(ext)
    big = call(mcp_client, "add_media", {"filename": "g.png", "data_base64": "A" * 14_100_000}, token=token)
    assert big["isError"] and "10 MB" in text_of(big)


def test_add_media_refuses_svg(mcp_client, tokens):
    token = tokens("claude")
    svg = base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"/>').decode()
    for name in ("logo.svg", "LOGO.SVG"):
        r = call(mcp_client, "add_media", {"filename": name, "data_base64": svg}, token=token)
        assert r["isError"] and "SVG" in text_of(r) and "PNG" in text_of(r)
    tool = next(t for t in list_tools(mcp_client) if t["name"] == "add_media")
    assert "svg senza script" not in tool["description"] and "NON sono ammessi" in tool["description"]


def list_tools(client):
    _, msg = rpc(client, "tools/list")
    return msg["result"]["tools"]


def test_review_token_redrafts_an_approved_note_through_mcp(mcp_client, tokens):
    token = tokens("claude", review=True)
    out = call(mcp_client, "add_notes", {"notes": [note_args("r", "uno", external_id="r1")]}, token=token)
    nid = out["structuredContent"]["results"][0]["note_id"]
    mcp_client.post("/api/hub/drafts/approve", json={"note_ids": [nid]})
    assert not call(mcp_client, "get_note", {"note_id": nid}, token=token)["structuredContent"]["draft"]

    # add_notes con lo stesso external_id e un contenuto diverso
    call(mcp_client, "add_notes", {"notes": [note_args("r", "due", external_id="r1")]}, token=token)
    assert call(mcp_client, "get_note", {"note_id": nid}, token=token)["structuredContent"]["draft"]

    # update_note su una nota approvata di nuovo
    mcp_client.post("/api/hub/drafts/approve", json={"note_ids": [nid]})
    call(mcp_client, "update_note", {"note_id": nid, "fields": {"Back": "tre"}}, token=token)
    got = call(mcp_client, "get_note", {"note_id": nid}, token=token)["structuredContent"]
    assert got["draft"] and got["fields"]["Back"] == "tre"


def test_external_id_pattern_and_size_limits_over_mcp(mcp_client, tokens):
    token = tokens("claude")
    for bad in ("con spazio", "a*b", "x" * 201):
        r = call(mcp_client, "add_notes", {"notes": [note_args("x", external_id=bad)]}, token=token)
        assert r["isError"], bad
    big = call(mcp_client, "add_notes", {"notes": [note_args("g", "x" * (200 * 1024 + 1))]}, token=token)
    assert big["isError"] and "200 KB" in text_of(big)
    total = call(mcp_client, "add_notes", {"notes": [note_args(f"n{i}", "x" * (190 * 1024)) for i in range(11)]}, token=token)
    assert total["isError"] and "2 MB" in text_of(total)
    patch = call(mcp_client, "update_note", {"note_id": 1, "fields": {"Back": "x" * (200 * 1024 + 1)}}, token=token)
    assert patch["isError"]


# ---- permessi ---------------------------------------------------------------------------------------


def test_read_scope_can_only_read(mcp_client, tokens):
    token = tokens("lettore", scope="read")
    for name in READ_ONLY - {"get_note"}:
        assert not call(mcp_client, name, {"query": "ser"} if name == "search_notes" else {}, token=token)["isError"], name
    before = mcp_client.get("/api/hub/summary").json()
    writes = {
        "add_notes": {"notes": [note_args("zz")]},
        "update_note": {"note_id": 1, "fields": {"Back": "x"}},
        "create_deck": {"name": "Vietato"},
        "sync_now": {},
        "add_media": {"filename": "a.png", "data_base64": PNG_B64},
    }
    for name, args in writes.items():
        r = call(mcp_client, name, args, token=token)
        assert r["isError"] and "scope «read»" in text_of(r) and "`write`" in text_of(r), name
    # niente è stato scritto
    assert mcp_client.get("/api/search/notes?q=zz").json()["total"] == 0
    assert call(mcp_client, "list_decks", token=token)["structuredContent"]["result"]
    assert all(d["full_name"] != "Vietato" for d in call(mcp_client, "list_decks")["structuredContent"]["result"])
    assert mcp_client.get("/api/hub/summary").json() == before


def test_in_process_client_without_identity_is_denied(mcp_client):
    """Chi non passa da /mcp (client in memoria) non ha un'identità: niente, deny by default."""

    async def go():
        async with Client(mcp_client.app.state.mcp.server) as c:
            return await c.call_tool("list_decks", {})

    result = asyncio.run(go())
    assert result.is_error and "non autenticato" in result.content[0].text


def test_no_destructive_tool_names(mcp_client):
    for forbidden in ("delete", "remove", "discard", "approve", "full_sync", "notetype_create", "tags"):
        assert not any(forbidden in n for n in EXPECTED_TOOLS - {"list_notetypes"}), forbidden


# ---- sync, collezione occupata -------------------------------------------------------------------------


def test_writes_request_a_sync_soon(mcp_client, tokens, monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_client.app.state.sync, "request_soon", lambda: calls.append(1))
    token = tokens("claude")
    call(mcp_client, "add_notes", {"notes": [note_args("s1")], "dry_run": True}, token=token)
    assert calls == []  # dry_run non scrive
    nid = call(mcp_client, "add_notes", {"notes": [note_args("s1")]}, token=token)["structuredContent"]["results"][0]["note_id"]
    call(mcp_client, "update_note", {"note_id": nid, "fields": {"Back": "y"}}, token=token)
    call(mcp_client, "create_deck", {"name": "Sincro"}, token=token)
    call(mcp_client, "add_media", {"filename": "s.png", "data_base64": PNG_B64}, token=token)
    assert len(calls) == 4
    call(mcp_client, "list_decks", token=token)
    call(mcp_client, "search_notes", token=token)
    assert len(calls) == 4  # le letture no


def test_sync_now_explains_what_to_do(mcp_client, tokens):
    out = call(mcp_client, "sync_now", token=tokens("claude"))
    assert out["isError"] and "AnkiWeb" in text_of(out) and "app" in text_of(out)


def test_busy_collection_says_retry(mcp_client, tokens):
    token = tokens("claude")
    manager = mcp_client.app.state.manager
    manager.busy_timeout = 0.05
    release = threading.Event()
    held = threading.Event()

    def hold():
        with manager.use():
            held.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(5)
    try:
        for name, args in [("list_decks", {}), ("add_notes", {"notes": [note_args("busy")]})]:
            r = call(mcp_client, name, args, token=token)
            assert r["isError"] and "occupata" in text_of(r) and "riprova" in text_of(r), name
    finally:
        release.set()
        t.join()
    assert not call(mcp_client, "list_decks", token=token)["isError"]


# ---- client dell'SDK su un uvicorn vero ---------------------------------------------------------------------


def serve(app):
    """Avvia l'app su una porta locale (solo loopback) e restituisce (url, server, thread)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    return f"http://127.0.0.1:{port}", server, thread


@pytest.fixture
def live_server(seeded):
    """Il backend su una porta locale: così passano le due versioni del protocollo e le
    risposte in streaming, come per un client vero."""
    settings, _ = seeded
    url, server, thread = serve(create_app(settings))
    yield url
    server.should_exit = True
    thread.join(10)


@pytest.mark.parametrize("mode", ["legacy", "modern"])
def test_sdk_client_over_real_http(live_server, mode):
    async def go():
        http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"})
        kwargs = {"mode": "legacy"} if mode == "legacy" else {}
        async with http, Client(streamable_http_client(f"{live_server}/mcp", http_client=http), **kwargs) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            decks = await c.call_tool("list_decks", {})
            dry = await c.call_tool(
                "add_notes", {"notes": [note_args("sdk", external_id="sdk-1")], "dry_run": True}
            )
            return c.protocol_version, names, decks, dry

    version, names, decks, dry = asyncio.run(go())
    assert version == ("2025-11-25" if mode == "legacy" else "2026-07-28")
    assert names == EXPECTED_TOOLS
    assert not decks.is_error and not dry.is_error
    assert dry.structured_content["created"] == 1 and dry.structured_content["dry_run"] is True


def test_sdk_client_wrong_token_is_refused(live_server):
    async def go():
        http = httpx2.AsyncClient(headers={"Authorization": "Bearer sbagliato"})
        async with http, Client(streamable_http_client(f"{live_server}/mcp", http_client=http)):
            pass

    with pytest.raises(Exception):  # noqa: B017 - l'SDK solleva il suo errore di trasporto
        asyncio.run(go())


def test_sse_response_is_streamed_not_buffered(live_server):
    """Una POST che risponde in SSE arriva intera e subito: niente compressione né
    bufferizzazione di mezzo (`Content-Encoding` assente, `no-transform`)."""
    with httpx2.Client(headers=headers_for(TOKEN)) as c:
        with c.stream(
            "POST", f"{live_server}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept-Encoding": "gzip"},
        ) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            assert "content-encoding" not in r.headers
            assert "no-transform" in r.headers["cache-control"]
            start = time.monotonic()
            body = b"".join(r.iter_raw())
            assert time.monotonic() - start < 5
    assert b"list_decks" in body


def test_the_middleware_stack_does_not_buffer_streams(seeded):
    """Un'eventuale risposta in streaming (SSE) esce a pezzi mentre viene prodotta: né il
    limite al body né il middleware di header e log la tengono finché non è finita."""
    from starlette.responses import StreamingResponse

    settings, _ = seeded
    app = create_app(settings)

    async def slow():
        yield b"data: uno\n\n"
        await asyncio.sleep(1.5)
        yield b"data: due\n\n"

    app.add_api_route("/mcp-prova-stream", lambda: StreamingResponse(slow(), media_type="text/event-stream"))
    url, server, thread = serve(app)
    try:
        with httpx2.Client() as c, c.stream("GET", f"{url}/mcp-prova-stream") as r:
            start = time.monotonic()
            chunks = iter(r.iter_raw())
            assert next(chunks) == b"data: uno\n\n"
            assert time.monotonic() - start < 1.0  # il primo pezzo arriva subito
            assert b"due" in b"".join(chunks)
            assert "content-encoding" not in r.headers
    finally:
        server.should_exit = True
        thread.join(10)
