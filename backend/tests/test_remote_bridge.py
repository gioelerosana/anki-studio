"""Ponte del telecomando (app/remote_bridge.py): l'app desktop si mostra al telefono attraverso il
server, con un token di scope `remote` che non serve a nient'altro."""

import json
import logging
import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect
from websockets.sync.client import connect as ws_connect

from app.config import Settings
from app.main import create_app
from app.remote_bridge import BridgeConfigError, normalize_server_url, websocket_url
from app.schemas import REMOTE_MAX_DECKS, RemoteScreenState
from app.security import DESKTOP_HEADER

from .conftest import TOKEN

KEY = "chiave-del-desktop-" + "k" * 32
DESK = {DESKTOP_HEADER: KEY}
LOCAL_SCREEN = "/api/remote?role=screen&screen_id=finestra-desktop-1"
BRIDGE = "/api/desktop/remote-bridge"


def _deck(i, children=()):
    return {"id": i, "name": f"Mazzo {i}", "counts": {"new": 1, "learning": 0, "review": 2}, "children": list(children)}


def _state(**over):
    state = {
        "view": "study",
        "deck_id": 1,
        "deck_name": "Spagnolo::Verbi",
        "card_id": 42,
        "revealed": False,
        "queue": "new",
        "counts": {"new": 3, "learning": 0, "review": 0},
        "button_labels": ["<1m", "<6m", "<10m", "4g"],
    }
    state.update(over)
    return state


# ---- token con scope `remote` -------------------------------------------------------------


def test_remote_token_only_opens_the_screen_role(client, make_token):
    headers, _ = make_token("portatile", scope="remote")
    with client.websocket_connect("/api/remote?role=screen&screen_id=ponte-desktop-1", headers=headers) as ws:
        assert ws.receive_json() == {"type": "remotes", "count": 0}
    # fare da telefono vorrebbe dire pilotare lo studio: no
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/remote?role=remote", headers=headers) as ws:
            ws.receive_json()


def test_read_and_write_tokens_stay_out_of_the_remote(client, make_token):
    for scope in ("read", "write"):
        headers, _ = make_token(f"agente-{scope}", scope=scope)
        for role in ("screen&screen_id=ponte-desktop-1", "remote"):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(f"/api/remote?role={role}", headers=headers) as ws:
                    ws.receive_json()


def test_remote_token_cannot_use_rest_or_mcp(client, make_token):
    headers, _ = make_token("portatile", scope="remote")
    assert client.get("/api/decks", headers=headers).status_code == 403
    assert client.get("/api/sync", headers=headers).status_code == 403
    assert client.get("/api/tokens", headers=headers).status_code == 403
    assert client.post("/api/hub/notes/batch", json={}, headers=headers).status_code == 403
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    mcp_headers = {**headers, "Accept": "application/json, text/event-stream"}
    r = client.post("/mcp", json=rpc, headers=mcp_headers)
    assert r.status_code == 403
    assert "telecomando" in r.json()["detail"]


def test_remote_token_scope_round_trips(client, make_token):
    _, body = make_token("portatile", scope="remote")
    assert body["scope"] == "remote"
    listed = {t["name"]: t["scope"] for t in client.get("/api/tokens").json()}
    assert listed["portatile"] == "remote"


# ---- stato dello schermo: `decks`, `source`, `null` ---------------------------------------


def test_decks_field_is_validated_and_limited():
    ok = RemoteScreenState.model_validate(_state(view="decks", decks=[_deck(1, [_deck(2)])]))
    assert ok.decks[0].children[0].id == 2 and ok.source == "browser"
    with pytest.raises(ValidationError):
        RemoteScreenState.model_validate(_state(decks=[{"id": 1, "name": "senza conteggi"}]))
    # troppi mazzi, anche se sparsi fra i figli
    many = [_deck(i, [_deck(10_000 + i)]) for i in range(REMOTE_MAX_DECKS // 2 + 1)]
    with pytest.raises(ValidationError):
        RemoteScreenState.model_validate(_state(decks=many))
    # troppo profondo
    deep = _deck(0)
    for i in range(1, 40):
        deep = _deck(i, [deep])
    with pytest.raises(ValidationError):
        RemoteScreenState.model_validate(_state(decks=[deep]))
    with pytest.raises(ValidationError):
        RemoteScreenState.model_validate(_state(source="altro"))


def test_screen_can_publish_decks_and_null(client):
    with client.websocket_connect("/api/remote?role=remote") as phone:
        assert phone.receive_json()["screen"] is None
        with client.websocket_connect("/api/remote?role=screen&screen_id=schermo-1234") as screen:
            screen.receive_json()
            screen.send_json({"type": "state", "state": _state(view="decks", decks=[_deck(7)]), "claim": True})
            msg = phone.receive_json()
            assert msg["screen"]["decks"][0]["id"] == 7
            # null: lo schermo c'è ma non ha niente da comandare
            screen.send_json({"type": "state", "state": None, "claim": False})
            assert phone.receive_json() == {"type": "state", "screen": None}


# ---- configurazione (rotte solo desktop) ---------------------------------------------------


def test_url_rules():
    assert normalize_server_url(" https://anki.jshep.xyz/ ") == "https://anki.jshep.xyz"
    assert normalize_server_url("http://127.0.0.1:8010") == "http://127.0.0.1:8010"
    for bad in ("http://anki.jshep.xyz", "ftp://x", "anki.jshep.xyz", "https://u:p@x", "https://x/?a=1"):
        with pytest.raises(BridgeConfigError):
            normalize_server_url(bad)
    assert websocket_url("https://anki.jshep.xyz", "desktop-1") == (
        "wss://anki.jshep.xyz/api/remote?role=screen&screen_id=desktop-1"
    )


def test_bridge_routes_exist_only_on_the_desktop(client):
    assert client.get(BRIDGE).status_code == 404


def _desktop_settings(tmp_path, **over):
    return Settings(
        anki_data_dir=tmp_path / "desktop",
        anki_desktop_key=KEY,
        anki_api_token=None,
        anki_auto_sync_minutes=0,
        anki_sync_on_startup=False,
        ankiweb_username=None,
        ankiweb_password=None,
        **over,
    )


def test_bridge_routes_need_the_desktop_key(tmp_path):
    with TestClient(create_app(_desktop_settings(tmp_path)), base_url="http://127.0.0.1:47613") as c:
        assert c.get(BRIDGE).status_code == 401
        assert c.get(BRIDGE, headers={"Authorization": "Bearer ask_qualcosa"}).status_code == 401
        res = c.get(BRIDGE, headers=DESK)
        assert res.status_code == 200
        assert res.json()["status"] == "off" and res.json()["token_set"] is False
        bad = c.put(BRIDGE, json={"server_url": "http://anki.jshep.xyz", "token": "ask_" + "x" * 20}, headers=DESK)
        assert bad.status_code == 400
        bad = c.put(BRIDGE, json={"server_url": "https://anki.jshep.xyz", "token": "x" * 20}, headers=DESK)
        assert bad.status_code == 400
        # da un'altra origine no, come le altre modifiche
        cross = c.put(
            BRIDGE,
            json={"server_url": "https://anki.jshep.xyz", "enabled": False},
            headers={**DESK, "Sec-Fetch-Site": "cross-site"},
        )
        assert cross.status_code == 403


# ---- il ponte contro un server vero ---------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    """Il backend «server» su uvicorn vero, in un thread: il ponte ci arriva via rete."""

    def __init__(self, settings: Settings, port: int) -> None:
        self.settings = settings
        self.port = port
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        config = uvicorn.Config(
            create_app(self.settings), host="127.0.0.1", port=self.port, log_config=None, lifespan="on"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        _wait(lambda: self.server.started, "avvio del server")

    def stop(self) -> None:
        assert self.server and self.thread
        self.server.should_exit = True
        self.thread.join(timeout=30)
        assert not self.thread.is_alive()


def _wait(predicate, what: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"timeout: {what}")


def _phone(server: LiveServer):
    return ws_connect(
        f"ws://127.0.0.1:{server.port}/api/remote?role=remote",
        additional_headers={"Authorization": f"Bearer {TOKEN}"},
    )


def _phone_until(phone, predicate, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        msg = json.loads(phone.recv(timeout=max(0.1, deadline - time.monotonic())))
        if msg.get("type") == "state" and predicate(msg["screen"]):
            return msg["screen"]


@pytest.fixture
def live_server(seeded):
    settings, _ = seeded
    server = LiveServer(settings, _free_port())
    server.start()
    yield server
    if server.thread and server.thread.is_alive():
        server.stop()


def test_bridge_end_to_end(live_server, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    plain = httpx.post(
        f"{live_server.url}/api/tokens",
        json={"name": "Portatile", "scope": "remote"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()["token"]

    app = create_app(_desktop_settings(tmp_path))
    bridge = app.state.bridge
    bridge.min_delay, bridge.max_delay = 0.05, 0.3  # riconnessione rapida per il test
    with TestClient(app, base_url="http://127.0.0.1:47613") as desk:
        status = lambda: desk.get(BRIDGE, headers=DESK).json()  # noqa: E731
        with desk.websocket_connect(LOCAL_SCREEN, headers=DESK) as screen:
            assert screen.receive_json() == {"type": "remotes", "count": 0}
            screen.send_json({"type": "state", "state": _state(view="decks", decks=[_deck(1)]), "claim": True})

            res = desk.put(BRIDGE, json={"server_url": live_server.url + "/", "token": plain}, headers=DESK)
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["token_set"] is True and "token" not in body and plain not in res.text
            assert body["server_url"] == live_server.url
            _wait(lambda: status()["status"] == "connected", "ponte collegato")

            # stato locale → telefono, con l'etichetta della sorgente e i mazzi del desktop
            with _phone(live_server) as phone:
                seen = _phone_until(phone, lambda s: s is not None)
                assert seen["source"] == "desktop" and seen["view"] == "decks"
                assert seen["decks"][0]["id"] == 1
                assert screen.receive_json() == {"type": "remotes", "count": 1}
                _wait(lambda: status()["remotes"] == 1, "telefoni contati")

                # comando dal telefono → schermata locale
                phone.send(json.dumps({"type": "command", "command": {"action": "open_deck", "deck_id": 1}}))
                cmd = screen.receive_json()
                assert cmd["type"] == "command" and cmd["command"]["action"] == "open_deck"

                screen.send_json({"type": "state", "state": _state(), "claim": True})
                seen = _phone_until(phone, lambda s: s is not None and s["view"] == "study")
                assert seen["card_id"] == 42
                phone.send(json.dumps({"type": "command", "command": {"action": "answer", "rating": 3, "card_id": 42}}))
                assert screen.receive_json()["command"]["rating"] == 3

            assert screen.receive_json() == {"type": "remotes", "count": 0}

            # il server cade: il ponte riprova da solo, il desktop resta usabile
            live_server.stop()
            _wait(lambda: status()["status"] == "retrying", "ponte in riconnessione")
            assert status()["last_error"]
            assert desk.get("/api/decks", headers=DESK).status_code == 200

            live_server.start()
            _wait(lambda: status()["status"] == "connected", "ponte ricollegato", timeout=20)
            with _phone(live_server) as phone:
                seen = _phone_until(phone, lambda s: s is not None)
                assert seen["view"] == "study" and seen["source"] == "desktop"
                assert screen.receive_json() == {"type": "remotes", "count": 1}

            # Scollega: subito, e il token sparisce dal disco
            res = desk.delete(BRIDGE, headers=DESK)
            assert res.json()["status"] == "off" and res.json()["token_set"] is False
            saved = json.loads(bridge.path.read_text())
            assert saved["token"] is None and saved["screen_id"].startswith("desktop-")
            assert os.stat(bridge.path).st_mode & 0o777 == 0o600

    # spento il desktop: nessun task del ponte rimasto in giro
    assert bridge._task is None
    # mai il token nei log, neanche nei record grezzi (prima del filtro dei segreti)
    assert plain not in caplog.text
    for record in caplog.records:
        assert plain not in record.getMessage()


def test_bridge_restarts_from_saved_config_and_stops_cleanly(live_server, tmp_path):
    plain = httpx.post(
        f"{live_server.url}/api/tokens",
        json={"name": "Portatile", "scope": "remote"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()["token"]
    settings = _desktop_settings(tmp_path)
    with TestClient(create_app(settings), base_url="http://127.0.0.1:47613") as desk:
        desk.put(BRIDGE, json={"server_url": live_server.url, "token": plain}, headers=DESK)
        _wait(lambda: desk.get(BRIDGE, headers=DESK).json()["status"] == "connected", "collegato")
        screen_id = json.loads(settings.remote_bridge_path.read_text())["screen_id"]

    # riavvio dell'app: riparte da solo con lo stesso screen_id (sostituisce la connessione vecchia)
    with TestClient(create_app(settings), base_url="http://127.0.0.1:47613") as desk:
        _wait(lambda: desk.get(BRIDGE, headers=DESK).json()["status"] == "connected", "ricollegato")
        assert json.loads(settings.remote_bridge_path.read_text())["screen_id"] == screen_id
        # Scollega senza dimenticare il token (enabled=false): token ancora impostato
        res = desk.put(BRIDGE, json={"server_url": live_server.url, "enabled": False}, headers=DESK)
        assert res.json()["status"] == "off" and res.json()["token_set"] is True


def test_rejected_token_backs_off(live_server, tmp_path):
    app = create_app(_desktop_settings(tmp_path))
    app.state.bridge.min_delay = 0.05
    with TestClient(app, base_url="http://127.0.0.1:47613") as desk:
        desk.put(BRIDGE, json={"server_url": live_server.url, "token": "ask_" + "z" * 43}, headers=DESK)
        body = _wait(
            lambda: (b := desk.get(BRIDGE, headers=DESK).json())["status"] == "retrying" and b,
            "token rifiutato",
        )
        assert "rifiutato" in body["last_error"]
        # attesa lunga: i Bearer sbagliati contano per il limite ai tentativi del server
        assert body["retry_at"] - time.time() > 60
