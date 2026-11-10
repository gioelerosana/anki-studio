"""Telecomando: WebSocket /api/remote tra la schermata di studio e il telefono."""

import pytest
from starlette.websockets import WebSocketDisconnect

from .conftest import TOKEN

SCREEN = "/api/remote?role=screen&screen_id=schermo-computer-1"
REMOTE = "/api/remote?role=remote"


def _state(**over):
    state = {
        "deck_id": 1,
        "deck_name": "Spagnolo::Verbi",
        "done": False,
        "card_id": 42,
        "revealed": False,
        "queue": "new",
        "counts": {"new": 3, "learning": 0, "review": 0},
        "button_labels": ["<1m", "<6m", "<10m", "4g"],
        "has_audio": True,
        "can_undo": False,
        "busy": False,
    }
    state.update(over)
    return state


def test_remote_controls_screen(client):
    with client.websocket_connect(SCREEN) as screen:
        assert screen.receive_json() == {"type": "remotes", "count": 0}
        with client.websocket_connect(REMOTE) as phone:
            # nessuno schermo ha ancora mandato uno stato
            assert phone.receive_json() == {"type": "state", "screen": None}
            assert screen.receive_json() == {"type": "remotes", "count": 1}

            screen.send_json({"type": "state", "state": _state(), "claim": True})
            msg = phone.receive_json()
            assert msg["type"] == "state" and msg["screen"]["card_id"] == 42

            phone.send_json({"type": "command", "command": {"action": "reveal", "card_id": 42}})
            assert screen.receive_json() == {
                "type": "command",
                "command": {"action": "reveal", "rating": None, "card_id": 42},
            }
            phone.send_json(
                {"type": "command", "command": {"action": "answer", "rating": 3, "card_id": 42}}
            )
            assert screen.receive_json()["command"]["rating"] == 3

        # il telefono se n'è andato
        assert screen.receive_json() == {"type": "remotes", "count": 0}


def test_screen_leaving_clears_phone(client):
    with client.websocket_connect(REMOTE) as phone:
        assert phone.receive_json()["screen"] is None
        with client.websocket_connect(SCREEN) as screen:
            screen.receive_json()
            screen.send_json({"type": "state", "state": _state(), "claim": True})
            assert phone.receive_json()["screen"]["deck_id"] == 1
        assert phone.receive_json() == {"type": "state", "screen": None}
        # comando senza schermo: il telefono riceve di nuovo lo stato vuoto
        phone.send_json({"type": "command", "command": {"action": "undo"}})
        assert phone.receive_json() == {"type": "state", "screen": None}


def test_last_focused_screen_wins(client):
    other = "/api/remote?role=screen&screen_id=schermo-ipad-0002"
    with client.websocket_connect(REMOTE) as phone:
        phone.receive_json()
        with client.websocket_connect(SCREEN) as pc, client.websocket_connect(other) as ipad:
            pc.receive_json()
            ipad.receive_json()
            pc.send_json({"type": "state", "state": _state(deck_id=1), "claim": True})
            assert phone.receive_json()["screen"]["deck_id"] == 1
            ipad.send_json({"type": "state", "state": _state(deck_id=2), "claim": True})
            assert phone.receive_json()["screen"]["deck_id"] == 2
            # il computer aggiorna lo stato in background: non si riprende il telefono
            pc.send_json({"type": "state", "state": _state(deck_id=1, revealed=True), "claim": False})
            phone.send_json({"type": "command", "command": {"action": "replay"}})
            assert ipad.receive_json()["command"]["action"] == "replay"


def test_invalid_message_closes(client):
    with client.websocket_connect(REMOTE) as phone:
        phone.receive_json()
        phone.send_json({"type": "command", "command": {"action": "answer", "rating": 9}})
        with pytest.raises(WebSocketDisconnect) as exc:
            phone.receive_json()
        assert exc.value.code == 4400


def test_screen_role_is_checked(client):
    # un telefono non può fingersi schermo mandando comandi, e viceversa
    with client.websocket_connect(SCREEN) as screen:
        screen.receive_json()
        screen.send_json({"type": "command", "command": {"action": "undo"}})
        with pytest.raises(WebSocketDisconnect):
            screen.receive_json()


def test_requires_auth(client):
    del client.headers["Authorization"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(REMOTE):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(REMOTE, headers={"Authorization": "Bearer sbagliato"}):
            pass
    with client.websocket_connect(REMOTE, headers={"Authorization": f"Bearer {TOKEN}"}) as ok:
        assert ok.receive_json()["type"] == "state"


def test_screen_needs_id(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/remote?role=screen"):
            pass


def test_cookie_session_checks_origin(client):
    """Con il cookie di sessione conta l'origine: un'altra pagina del dominio non entra."""
    from app.security import SESSION_COOKIE

    del client.headers["Authorization"]
    cookie = client.app.state.signer.dumps("session", {"sub": "joe"}, 600)
    client.cookies.set(SESSION_COOKIE, cookie)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(REMOTE, headers={"Origin": "https://altro.jshep.xyz"}):
            pass
    with client.websocket_connect(REMOTE, headers={"Origin": "http://testserver"}) as ok:
        assert ok.receive_json()["type"] == "state"
