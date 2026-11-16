"""Eliminazione dei mazzi dalla PWA: riepilogo per la conferma e cancellazione come Anki desktop."""

from anki.collection import Collection


def _names(client):
    def walk(nodes):
        for n in nodes:
            yield n["full_name"]
            yield from walk(n["children"])

    return set(walk(client.get("/api/decks").json()))


def _add_subdeck(client, name="Spagnolo::Verbi::Irregolari"):
    """Un sottomazzo con una nota, creato dall'API dell'hub (stessa collezione aperta)."""
    deck = client.post("/api/hub/decks", json={"name": name}).json()
    did = deck["id"]
    notetype = next(t for t in client.get("/api/notetypes").json() if t["name"] == "Basic")
    r = client.post(
        "/api/notes",
        json={"deck_id": did, "notetype_id": notetype["id"], "fields": {"Front": "hacer", "Back": "fare"}},
    )
    assert r.status_code == 201, r.text
    return did


def test_info_counts_subdecks(client):
    _add_subdeck(client)
    info = client.get(f"/api/decks/{client.deck_id}").json()
    assert info["full_name"] == "Spagnolo::Verbi"
    assert info["filtered"] is False
    assert info["subdecks"] == 1
    assert info["cards"] == 4
    assert info["notes"] == 4


def test_delete_removes_deck_subdecks_and_cards(client):
    _add_subdeck(client)
    r = client.delete(f"/api/decks/{client.deck_id}")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted_cards": 4, "deleted_decks": 2}
    names = _names(client)
    assert "Spagnolo::Verbi" not in names
    assert "Spagnolo::Verbi::Irregolari" not in names
    # il genitore resta
    assert "Spagnolo" in names
    assert client.get("/api/search/notes?q=ser").json()["total"] == 0
    assert client.get(f"/api/decks/{client.deck_id}").status_code == 404


def test_delete_unknown_deck_is_404(client):
    assert client.delete("/api/decks/987654321").status_code == 404
    assert client.get("/api/decks/987654321").status_code == 404


def test_delete_filtered_deck_returns_cards_home(seeded):
    from fastapi.testclient import TestClient

    from app.main import create_app

    from .conftest import TOKEN

    settings, did = seeded
    col = Collection(str(settings.collection_path))
    fid = col.decks.new_filtered("Ripasso")
    deck = col.decks.get(fid)
    deck["terms"][0][0] = "deck:Spagnolo::Verbi"
    col.decks.save(deck)
    col.sched.rebuild_filtered_deck(fid)
    assert col.card_count() == 3
    col.close()

    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        info = c.get(f"/api/decks/{fid}").json()
        assert info["filtered"] is True
        assert info["cards"] == 3
        r = c.delete(f"/api/decks/{fid}")
        assert r.status_code == 200
        assert r.json()["deleted_cards"] == 0
        assert "Ripasso" not in _names(c)
        # le carte sono tornate a casa, intatte
        assert c.get(f"/api/decks/{did}").json()["cards"] == 3
