"""App desktop: la chiave dell'avvio (ANKI_DESKTOP_KEY) nell'header al posto di Authentik."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.security import DESKTOP_HEADER

KEY = "chiave-del-desktop-" + "x" * 32


@pytest.fixture
def desktop(seeded, tmp_path):
    settings, did = seeded
    settings = settings.model_copy(update={"anki_desktop_key": KEY, "anki_api_token": None})
    with TestClient(create_app(settings), base_url="http://127.0.0.1:47613") as c:
        c.deck_id = did
        yield c


def test_chiave_giusta_apre_la_collezione(desktop):
    res = desktop.get("/api/auth/me", headers={DESKTOP_HEADER: KEY})
    assert res.status_code == 200
    assert res.json()["name"] == "Questo computer"
    assert desktop.get("/api/decks", headers={DESKTOP_HEADER: KEY}).status_code == 200


def test_senza_chiave_o_con_quella_sbagliata_401(desktop):
    assert desktop.get("/api/decks").status_code == 401
    assert desktop.get("/api/decks", headers={DESKTOP_HEADER: "x" * 40}).status_code == 401


def test_troppe_chiavi_sbagliate_bloccano(desktop):
    for _ in range(20):
        desktop.get("/api/decks", headers={DESKTOP_HEADER: "y" * 40})
    # bloccato anche con quella giusta: chi indovina non deve accorgersene
    assert desktop.get("/api/decks", headers={DESKTOP_HEADER: KEY}).status_code == 429


def test_modifiche_da_altre_origini_rifiutate(desktop):
    headers = {DESKTOP_HEADER: KEY, "Sec-Fetch-Site": "cross-site"}
    res = desktop.post("/api/sync", headers=headers)
    assert res.status_code == 403


SCREEN = "/api/remote?role=screen&screen_id=schermo-computer-1"


def test_websocket_con_la_chiave(desktop):
    with desktop.websocket_connect(SCREEN, headers={DESKTOP_HEADER: KEY}) as ws:
        assert ws.receive_json() == {"type": "remotes", "count": 0}
    with pytest.raises(WebSocketDisconnect):
        with desktop.websocket_connect(SCREEN) as ws:
            ws.receive_json()


def test_non_va_con_oidc_o_dev_login(tmp_path):
    with pytest.raises(ValidationError):
        Settings(anki_data_dir=tmp_path, anki_desktop_key=KEY, anki_dev_login=True)


def test_chiave_troppo_corta(tmp_path):
    with pytest.raises(ValidationError):
        Settings(anki_data_dir=tmp_path, anki_desktop_key="corta")
