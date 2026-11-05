"""La collezione di sviluppo deve restare studiabile da cima a fondo via API."""

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from .conftest import TOKEN

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_dev.py"


def _load_seed():
    spec = importlib.util.spec_from_file_location("seed_dev", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_refuses_and_backs_up(tmp_path):
    seed = _load_seed()
    assert seed.main(["--data-dir", str(tmp_path)]) == 0
    assert seed.main(["--data-dir", str(tmp_path)]) == 1  # non sovrascrive
    (tmp_path / "sync_auth.json").write_text("{}")
    assert seed.main(["--data-dir", str(tmp_path), "--force"]) == 0
    backups = list(tmp_path.glob("backup-seed-*"))
    assert len(backups) == 1
    assert (backups[0] / "collection.anki2").exists()
    assert (backups[0] / "sync_auth.json").exists()
    assert not (tmp_path / "sync_auth.json").exists()


def test_seed_is_fully_studyable(tmp_path):
    assert _load_seed().main(["--data-dir", str(tmp_path)]) == 0
    settings = Settings(
        anki_api_token=TOKEN,
        anki_data_dir=tmp_path,
        anki_auto_sync_minutes=0,
        anki_sync_on_startup=False,
    )
    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        tree = c.get("/api/decks").json()
        names = {d["name"] for d in tree}
        assert {"Lingue", "Scienze", "Default", "Archivio"} <= names
        lingue = next(d for d in tree if d["name"] == "Lingue")
        assert lingue["counts"]["learning"] > 0 and lingue["counts"]["review"] > 0

        seen_queues, seen_av, seen_media = set(), set(), False
        for deck in tree:
            if deck["name"] == "Archivio":
                assert c.get(f"/api/decks/{deck['id']}/study").json()["done"]
                continue
            state = c.get(f"/api/decks/{deck['id']}/study").json()
            for _ in range(200):
                if state["done"]:
                    break
                card = state["card"]
                seen_queues.add(card["queue"])
                for av in card["question_av"] + card["answer_av"]:
                    seen_av.add(av["type"])
                    if av["type"] == "sound":
                        assert c.get(av["url"]).status_code == 200, av["url"]
                if "/api/media/" in card["question_html"] + card["answer_html"]:
                    seen_media = True
                r = c.post(
                    f"/api/decks/{deck['id']}/study/answer",
                    json={"card_id": card["card_id"], "rating": 4, "time_taken_ms": 1000},
                )
                assert r.status_code == 200, r.text
                state = r.json()
            assert state["done"]
        assert seen_queues == {"new", "learning", "review"}
        assert seen_av == {"sound", "tts"}
        assert seen_media
        assert c.get("/api/media/citt%C3%A0%20notte.png").status_code == 200
