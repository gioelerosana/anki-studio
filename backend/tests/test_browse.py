import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from .conftest import TOKEN

SEED = Path(__file__).resolve().parent.parent / "scripts" / "seed_dev.py"


@pytest.fixture
def seeded_client(tmp_path):
    spec = importlib.util.spec_from_file_location("seed_dev", SEED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--data-dir", str(tmp_path)]) == 0
    settings = Settings(
        anki_api_token=TOKEN, anki_data_dir=tmp_path,
        anki_auto_sync_minutes=0, anki_sync_on_startup=False,
    )
    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        yield c


def _deck(c, name):
    def walk(nodes):
        for n in nodes:
            if n["full_name"] == name:
                return n
            if (f := walk(n["children"])):
                return f
    return walk(c.get("/api/decks").json())


def test_search_notes(seeded_client):
    c = seeded_client
    r = c.get("/api/search/notes", params={"q": "tag:spagnolo::verbi", "limit": 3})
    body = r.json()
    assert body["total"] == 8 and len(body["notes"]) == 3
    n = body["notes"][0]
    assert n["notetype_name"] == "Vocabolo" and n["deck_name"] == "Lingue::Spagnolo::Verbi"
    assert "spagnolo::verbi" in n["tags"] and n["card_ids"]
    page2 = c.get("/api/search/notes", params={"q": "tag:spagnolo::verbi", "limit": 3, "offset": 3}).json()
    assert {x["id"] for x in page2["notes"]}.isdisjoint({x["id"] for x in body["notes"]})
    assert c.get("/api/search/notes", params={"q": "hablar"}).json()["total"] == 1
    assert c.get("/api/search/notes", params={"q": "deck:("}).status_code == 400
    assert c.get("/api/search/notes").json()["total"] == 34


def test_tags(seeded_client):
    tags = seeded_client.get("/api/tags").json()
    assert "spagnolo::verbi" in tags and "chimica" in tags


def test_stats(seeded_client):
    c = seeded_client
    s = c.get("/api/stats").json()
    assert s["cards"]["total"] == 47
    assert s["cards"]["suspended"] == 1 and s["cards"]["buried"] == 1
    assert s["cards"]["learning"] >= 2 and s["cards"]["young"] > 0
    assert len(s["reviews"]) == 30 and s["reviews"][-1]["day"] == 0
    assert s["reviews"][-1]["reviews"] >= 3  # le risposte del seed sono di oggi
    assert s["forecast"][0]["due"] > 0
    verbi = _deck(c, "Lingue::Spagnolo::Verbi")
    sv = c.get("/api/stats", params={"deck_id": verbi["id"], "days": 7}).json()
    assert sv["cards"]["total"] == 8 and len(sv["reviews"]) == 7
    assert c.get("/api/stats", params={"deck_id": 1234}).status_code == 404


def test_deck_options_and_extend_limits(seeded_client):
    c = seeded_client
    nomi = _deck(c, "Lingue::Spagnolo::Nomi")
    o = c.get(f"/api/decks/{nomi['id']}/options").json()
    assert o["preset_name"] and o["new_per_day"] == 20 and not o["filtered"]
    assert o["learn_steps_min"]
    # limite a 3 nuove al giorno (Nomi ne ha 10), poi "studia altre 4 oggi"
    with c.app.state.manager.use() as col:
        conf = col.decks.config_dict_for_deck_id(nomi["id"])
        conf["new"]["perDay"] = 3
        col.decks.update_config(conf)
    assert c.get(f"/api/decks/{nomi['id']}/study").json()["counts"]["new"] == 3
    s = c.post(f"/api/decks/{nomi['id']}/extend-limits", json={"new": 4}).json()
    assert s["counts"]["new"] == 7 and s["deck_name"] == "Lingue::Spagnolo::Nomi"
