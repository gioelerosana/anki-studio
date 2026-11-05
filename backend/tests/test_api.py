from fastapi.testclient import TestClient


def test_requires_token(client: TestClient):
    r = client.get("/api/decks", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert client.get("/api/health").status_code == 200


def test_deck_tree(client: TestClient):
    tree = client.get("/api/decks").json()
    spagnolo = next(d for d in tree if d["name"] == "Spagnolo")
    verbi = spagnolo["children"][0]
    assert verbi["full_name"] == "Spagnolo::Verbi"
    assert verbi["id"] == client.deck_id
    assert verbi["counts"]["new"] == 3


def test_study_flow(client: TestClient):
    did = client.deck_id
    s = client.get(f"/api/decks/{did}/study").json()
    assert not s["done"]
    card = s["card"]
    assert card["queue"] == "new"
    assert len(card["button_labels"]) == 4
    assert '/api/media/pic.png' in card["question_html"]
    assert 'class="anki-play"' in card["answer_html"]
    assert card["answer_av"][0]["type"] == "sound"
    assert card["answer_av"][0]["url"].endswith(".mp3")

    # risposta "Bene" -> arriva la carta successiva
    r = client.post(
        f"/api/decks/{did}/study/answer",
        json={"card_id": card["card_id"], "rating": 3, "time_taken_ms": 4200},
    )
    assert r.status_code == 200, r.text
    nxt = r.json()
    assert nxt["card"]["card_id"] != card["card_id"]
    assert nxt["counts"]["new"] == 2

    # rispondere di nuovo alla stessa carta è un conflitto
    r = client.post(
        f"/api/decks/{did}/study/answer",
        json={"card_id": card["card_id"], "rating": 3, "time_taken_ms": 100},
    )
    assert r.status_code == 409

    # undo riporta in cima la prima carta
    undone = client.post(f"/api/decks/{did}/study/undo").json()
    assert undone["card"]["card_id"] == card["card_id"]

    stats = client.get("/api/stats/today").json()
    assert stats["reviews"] == 0  # la review è stata annullata


def test_bury_and_flag(client: TestClient):
    did = client.deck_id
    card = client.get(f"/api/decks/{did}/study").json()["card"]
    assert client.post(f"/api/cards/{card['card_id']}/flag", json={"flag": 2}).status_code == 204
    assert client.post(f"/api/cards/{card['card_id']}/bury").status_code == 204
    s = client.get(f"/api/decks/{did}/study").json()
    assert s["card"]["card_id"] != card["card_id"]
    assert s["counts"]["new"] == 2


def test_notes_crud(client: TestClient):
    types = client.get("/api/notetypes").json()
    basic = next(t for t in types if t["name"] == "Basic")
    assert [f["name"] for f in basic["fields"]] == ["Front", "Back"]

    r = client.post(
        "/api/notes",
        json={
            "deck_id": client.deck_id,
            "notetype_id": basic["id"],
            "fields": {"Front": "hablar", "Back": "parlare"},
            "tags": ["verbi"],
        },
    )
    assert r.status_code == 201, r.text
    note = r.json()
    assert len(note["card_ids"]) == 1

    dup = client.post(
        "/api/notes",
        json={"deck_id": client.deck_id, "notetype_id": basic["id"], "fields": {"Front": "hablar"}},
    )
    assert dup.status_code == 422

    bad = client.post(
        "/api/notes",
        json={"deck_id": client.deck_id, "notetype_id": basic["id"], "fields": {"Nope": "x"}},
    )
    assert bad.status_code == 422

    upd = client.patch(f"/api/notes/{note['id']}", json={"fields": {"Back": "parlare, dire"}})
    assert upd.json()["fields"]["Back"] == "parlare, dire"


def test_media(client: TestClient):
    assert client.get("/api/media/pic.png").content == b"\x89PNG fake"
    assert client.get("/api/media/missing.png").status_code == 404
    assert client.get("/api/media/..%2Fcollection.anki2").status_code in (400, 404)


def test_media_with_cookie(client: TestClient):
    token = client.headers.pop("Authorization")
    assert client.get("/api/media/pic.png").status_code == 401
    client.headers["Authorization"] = token
    client.post("/api/auth/session")
    client.headers.pop("Authorization")
    # TestClient usa http://testserver: il cookie è "secure", lo rimandiamo a mano
    r = client.get("/api/media/pic.png", cookies={"anki_token": token.split()[1]})
    assert r.status_code == 200


def test_sync_not_logged_in(client: TestClient):
    st = client.get("/api/sync").json()
    assert st["logged_in"] is False
    assert client.post("/api/sync").status_code == 401
