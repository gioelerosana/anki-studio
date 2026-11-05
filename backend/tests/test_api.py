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


def test_sync_not_logged_in(client: TestClient):
    st = client.get("/api/sync").json()
    assert st["logged_in"] is False
    assert client.post("/api/sync").status_code == 401


def test_italian_labels_and_deck_name(client: TestClient):
    s = client.get(f"/api/decks/{client.deck_id}/study").json()
    assert s["deck_name"] == "Spagnolo::Verbi"
    labels = s["card"]["button_labels"]
    assert labels[-1].endswith("g")  # "4g", non "4d"
    assert not any("⁨" in x or "⁩" in x for x in labels)
    assert "⁨" not in client.get("/api/stats/today").json()["summary"]


def test_undo_label_and_deck_switch(client: TestClient):
    did = client.deck_id
    s = client.get(f"/api/decks/{did}/study").json()
    assert s["undo_label"] is None
    r = client.post(
        f"/api/decks/{did}/study/answer",
        json={"card_id": s["card"]["card_id"], "rating": 3, "time_taken_ms": 1000},
    )
    assert r.json()["undo_label"]  # es. "Rispondi alla carta"

    # aprire un altro mazzo non deve rendere annullabile la "selezione del mazzo"
    other = next(d for d in client.get("/api/decks").json() if d["name"] == "Spagnolo")
    s2 = client.get(f"/api/decks/{other['id']}/study").json()
    assert s2["undo_label"] is None and s2["deck_name"] == "Spagnolo"
    assert client.post(f"/api/decks/{other['id']}/study/undo").status_code == 409


def test_bury_returns_next_card_with_deck_id(client: TestClient):
    did = client.deck_id
    card = client.get(f"/api/decks/{did}/study").json()["card"]
    r = client.post(f"/api/cards/{card['card_id']}/bury", params={"deck_id": did})
    assert r.status_code == 200
    assert r.json()["card"]["card_id"] != card["card_id"]
    assert r.json()["undo_label"]
    nxt = r.json()["card"]["card_id"]
    r = client.post(f"/api/cards/{nxt}/suspend", params={"deck_id": did})
    assert r.status_code == 200 and r.json()["counts"]["new"] == 1


def test_type_answer_and_css_urls(seeded):
    from anki.collection import Collection

    from app.main import create_app

    settings, did = seeded
    col = Collection(str(settings.collection_path))
    nt = col.models.by_name("Basic (type in the answer)")
    nt["css"] += '\n@font-face { font-family: x; src: url("_font.ttf"); }\n.a{background:url(data:x)}'
    col.models.update_dict(nt)
    n = col.new_note(nt)
    n["Front"], n["Back"] = "gatto", "cat"
    col.add_note(n, col.decks.id("Digitare"))
    tdid = col.decks.id_for_name("Digitare")
    col.close()

    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = "Bearer test-token-abcdefghijklmnop"
        card = c.get(f"/api/decks/{tdid}/study").json()["card"]
        assert 'url("/api/media/_font.ttf")' in card["css"]
        assert "url(data:x)" in card["css"]
        r = c.post(f"/api/cards/{card['card_id']}/type-answer", json={"typed": "cot"})
        html = r.json()["answer_html"]
        assert "typeGood" in html and "typeBad" in html and "[[type:" not in html
        r = c.post(f"/api/cards/{card['card_id']}/type-answer", json={"typed": "cat"})
        assert "typeBad" not in r.json()["answer_html"]
