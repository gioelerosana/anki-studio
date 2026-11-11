"""Hub delle flashcard: batch, idempotenza, anteprima, spostamenti e tag in blocco."""

import pytest

from .conftest import note_count

BATCH = "/api/hub/notes/batch"


def basic(front, back="r", deck="Spagnolo::Verbi", **extra):
    return {"deck": deck, "notetype": "Basic", "fields": {"Front": front, "Back": back}, **extra}


def post_batch(client, notes, headers=None, **opts):
    r = client.post(BATCH, json={"notes": notes, **opts}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def get_note(client, note_id):
    r = client.get(f"/api/notes/{note_id}")
    assert r.status_code == 200, r.text
    return r.json()


def card_queues(client, note_id):
    with client.app.state.manager.use() as col:
        return [col.get_card(c).queue for c in col.get_note(note_id).card_ids()]


# ---- batch ---------------------------------------------------------------------------


def test_batch_creates_with_deck_by_name_and_id(client):
    out = post_batch(
        client,
        [basic("hablar", "parlare"), basic("comer", deck=client.deck_id)],
    )
    assert (out["created"], out["errors"], out["dry_run"]) == (2, 0, False)
    first = out["results"][0]
    assert first["status"] == "created" and first["note_id"] and len(first["card_ids"]) == 1
    note = get_note(client, first["note_id"])
    assert note["fields"] == {"Front": "hablar", "Back": "parlare"}
    assert note_count(client) == 5
    # le note entrano subito: normali, con le carte attive
    assert card_queues(client, first["note_id"]) == [0]
    assert "hub::bozza" not in note["tags"]


def test_batch_per_note_errors_do_not_stop_the_others(client):
    out = post_batch(
        client,
        [
            basic("ok"),
            {"deck": "Spagnolo::Verbi", "notetype": "Basic", "fields": {"Nope": "x"}},
            {"deck": "Spagnolo::Verbi", "notetype": "Inesistente", "fields": {"Front": "x"}},
            basic("nuovo", deck="Mazzo che non c'è"),
            basic("   "),  # primo campo vuoto
            basic("dopo"),
        ],
    )
    statuses = [r["status"] for r in out["results"]]
    assert statuses == ["created", "error", "error", "error", "error", "created"]
    assert (out["created"], out["errors"]) == (2, 4)
    assert "Nope" in out["results"][1]["error"]
    assert "Inesistente" in out["results"][2]["error"]
    assert "create_missing_decks" in out["results"][3]["error"]
    assert "vuoto" in out["results"][4]["error"]
    assert note_count(client) == 5


def test_unknown_notetype_error_lists_the_available_ones(client):
    """I nomi dei tipi di nota dipendono dalla lingua della collezione: l'errore deve
    dire all'agente come correggersi."""
    out = post_batch(client, [{"deck": "D", "notetype": "Nome sbagliato", "fields": {"Front": "a"}}], create_missing_decks=True)
    err = out["results"][0]["error"]
    assert out["results"][0]["status"] == "error"
    assert "Disponibili" in err and "«Basic»" in err


def test_unknown_field_error_lists_the_valid_ones(client):
    out = post_batch(client, [{"deck": "D", "notetype": "Basic", "fields": {"Nope": "a"}}], create_missing_decks=True)
    err = out["results"][0]["error"]
    assert "Campi validi" in err and "«Front»" in err and "«Back»" in err


def test_batch_cap_is_100(client):
    assert client.post(BATCH, json={"notes": [basic(f"n{i}") for i in range(101)]}).status_code == 422
    assert client.post(BATCH, json={"notes": []}).status_code == 422
    out = post_batch(client, [basic(f"n{i}") for i in range(100)])
    assert out["created"] == 100


def test_create_missing_decks_is_idempotent(client):
    notes = [basic("a", deck="Nuovo::Sotto"), basic("b", deck="Nuovo::Sotto")]
    out = post_batch(client, notes, create_missing_decks=True)
    assert out["created"] == 2
    names = {d["full_name"] for d in _flat(client.get("/api/decks").json())}
    assert {"Nuovo", "Nuovo::Sotto"} <= names
    with client.app.state.manager.use() as col:
        assert len([d for d in col.decks.all_names_and_ids() if d.name == "Nuovo::Sotto"]) == 1


def _flat(tree):
    for d in tree:
        yield d
        yield from _flat(d["children"])


def test_dry_run_reports_without_writing(client):
    notes = [
        basic("uno", deck="Mazzo::Futuro"),
        basic("due"),
        basic("rotta", deck="Boh"),
    ]
    out = post_batch(client, notes, dry_run=True, create_missing_decks=True)
    assert out["dry_run"] is True and out["operation_id"] is None
    assert [r["status"] for r in out["results"]] == ["created", "created", "created"]
    assert all(r["note_id"] is None for r in out["results"])
    # nessuna nota, nessun mazzo, nessuna voce di undo
    assert note_count(client) == 3
    assert "Mazzo::Futuro" not in {d["full_name"] for d in _flat(client.get("/api/decks").json())}
    with client.app.state.manager.use() as col:
        assert "Aggiungi note da agente" != col.undo_status().undo
    # senza create_missing_decks l'esito è lo stesso che avrebbe la scrittura vera
    out = post_batch(client, [basic("x", deck="Boh")], dry_run=True)
    assert out["results"][0]["status"] == "error"


def test_dry_run_matches_the_real_run(client):
    notes = [basic("a", external_id="e1"), basic("a2"), basic("a2"), basic("a", external_id="e1")]
    dry = post_batch(client, notes, dry_run=True)
    real = post_batch(client, notes)
    assert [r["status"] for r in dry["results"]] == [r["status"] for r in real["results"]]
    assert [r["status"] for r in real["results"]] == ["created", "created", "duplicate", "error"]


def test_external_id_is_idempotent(client):
    first = post_batch(client, [basic("ir", "andare", external_id="verbo-ir")])
    nid = first["results"][0]["note_id"]
    assert "ext::verbo-ir" in get_note(client, nid)["tags"]

    again = post_batch(client, [basic("ir", "andare", external_id="verbo-ir")])
    assert again["results"][0] == {
        "index": 0, "status": "unchanged", "note_id": nid,
        "card_ids": first["results"][0]["card_ids"], "error": None,
    }
    assert again["unchanged"] == 1 and note_count(client) == 4

    changed = post_batch(client, [basic("ir", "marcharse", external_id="verbo-ir", tags=["verbi"])])
    assert changed["results"][0]["status"] == "updated" and changed["updated"] == 1
    note = get_note(client, nid)
    assert note["fields"]["Back"] == "marcharse"
    assert {"verbi", "ext::verbo-ir"} <= set(note["tags"])
    assert note_count(client) == 4

    # un tag aggiunto a mano dall'utente non viene tolto da un nuovo invio
    client.patch(f"/api/notes/{nid}", json={"tags": ["verbi", "ext::verbo-ir", "mio"]})
    post_batch(client, [basic("ir", "marcharse", external_id="verbo-ir", tags=["verbi"])])
    assert "mio" in get_note(client, nid)["tags"]


def test_external_id_other_notetype_and_repeated_in_batch(client):
    post_batch(client, [basic("a", external_id="x")])
    out = post_batch(
        client,
        [
            {"deck": "Spagnolo::Verbi", "notetype": "Cloze", "fields": {"Text": "{{c1::a}}"}, "external_id": "x"},
            basic("b", external_id="y"),
            basic("c", external_id="y"),
        ],
    )
    assert [r["status"] for r in out["results"]] == ["error", "created", "error"]
    assert "altro tipo" in out["results"][0]["error"]
    assert "ripetuto" in out["results"][2]["error"]


def test_duplicate_first_field_without_external_id(client):
    first = post_batch(client, [basic("ser", "essere")])  # "ser" c'è già dal seed? no: ha <img>
    assert first["created"] == 1
    out = post_batch(client, [basic("ser", "altro"), basic("nuova"), basic("nuova")])
    assert [r["status"] for r in out["results"]] == ["duplicate", "created", "duplicate"]
    assert out["duplicates"] == 2
    assert out["results"][0]["note_id"] == first["results"][0]["note_id"]
    # il duplicato nella stessa batch punta alla nota appena creata
    assert out["results"][2]["note_id"] == out["results"][1]["note_id"]
    assert note_count(client) == 5
    # con un external_id l'agente dice che è un'altra nota: si crea
    again = post_batch(client, [basic("ser", "altro", external_id="ser-2")])
    assert again["results"][0]["status"] == "created"


def test_cloze(client):
    out = post_batch(
        client,
        [
            {"deck": "Spagnolo::Verbi", "notetype": "Cloze", "fields": {"Text": "{{c1::Roma}} è in {{c2::Italia}}"}},
            {"deck": "Spagnolo::Verbi", "notetype": "Cloze", "fields": {"Text": "senza cloze"}},
        ],
    )
    assert [r["status"] for r in out["results"]] == ["created", "error"]
    assert len(out["results"][0]["card_ids"]) == 2
    assert "cloze" in out["results"][1]["error"].lower()


def test_notetype_by_id(client):
    notetypes = client.get("/api/notetypes").json()
    basic_id = next(n["id"] for n in notetypes if n["name"] == "Basic")
    out = post_batch(client, [{"deck": client.deck_id, "notetype": basic_id, "fields": {"Front": "x"}}])
    assert out["created"] == 1


def test_batch_is_one_undoable_operation(client):
    before = note_count(client)
    post_batch(client, [basic(f"n{i}") for i in range(5)], create_missing_decks=False)
    assert note_count(client) == before + 5
    with client.app.state.manager.use() as col:
        assert col.undo_status().undo == "Aggiungi note da agente"
        col.undo()
        assert col.note_count() == before


def test_batch_of_100_notes_is_one_undoable_operation(client):
    """Anki tiene solo 30 passi di undo: con 100 note la voce unica cadrebbe dalla pila se i
    passi non venissero fusi man mano."""
    before = note_count(client)
    out = post_batch(client, [basic(f"c{i}") for i in range(100)])
    assert out["created"] == 100 and note_count(client) == before + 100
    with client.app.state.manager.use() as col:
        assert col.undo_status().undo == "Aggiungi note da agente"
        col.undo()
        assert col.note_count() == before


def test_batch_updating_100_notes_is_one_undoable_operation(client, make_token):
    headers, _ = make_token("claude")
    notes = [basic(f"u{i}", "uno", external_id=f"u{i}") for i in range(100)]
    created = post_batch(client, notes, headers=headers)
    ids = [r["note_id"] for r in created["results"]]
    out = post_batch(client, [basic(f"u{i}", "due", external_id=f"u{i}") for i in range(100)], headers=headers)
    assert out["updated"] == 100
    with client.app.state.manager.use() as col:
        assert col.undo_status().undo == "Aggiungi note da agente"
        col.undo()  # una sola voce: torna tutto com'era prima dell'aggiornamento
    assert get_note(client, ids[0])["fields"]["Back"] == "uno"


def test_batch_with_nothing_to_write_leaves_no_undo_entry(client):
    with client.app.state.manager.use() as col:
        label = col.undo_status().undo
    post_batch(client, [basic("x", deck="Boh")])
    with client.app.state.manager.use() as col:
        assert col.undo_status().undo == label


def test_study_does_not_offer_to_undo_a_batch(client):
    post_batch(client, [basic("x")])
    state = client.get(f"/api/decks/{client.deck_id}/study").json()
    assert state["undo_label"] is None


def test_reserved_tags_from_the_request_are_ignored(client, make_token):
    headers, _ = make_token("claude")
    out = post_batch(
        client,
        [basic("t", tags=["utile", "AGENT::altro", "agent::altro", "ext::furbo", "con spazio"])],
        headers=headers,
    )
    tags = set(get_note(client, out["results"][0]["note_id"])["tags"])
    assert tags == {"utile", "con_spazio", "agent::claude"}


def test_hub_prefix_is_no_longer_reserved(client, make_token):
    """`hub::bozza` non ha più alcun significato speciale: è un tag come un altro."""
    headers, _ = make_token("claude")
    out = post_batch(client, [basic("t", tags=["hub::bozza"])], headers=headers)
    nid = out["results"][0]["note_id"]
    assert set(get_note(client, nid)["tags"]) == {"hub::bozza", "agent::claude"}
    assert card_queues(client, nid) == [0]
    assert client.post("/api/notes/tags", json={"note_ids": [nid], "remove": ["hub::bozza"]}).json() == {"updated": 1}
    assert set(get_note(client, nid)["tags"]) == {"agent::claude"}
    # restano riservati la provenienza e l'id dell'invio, e i loro genitori
    for body in ({"add": ["agent::x"]}, {"add": ["ext::x"]}, {"remove": ["agent"]}, {"remove": ["EXT"]}):
        assert client.post("/api/notes/tags", json={"note_ids": [nid], **body}).status_code == 422


# ---- anteprima -----------------------------------------------------------------------


def test_preview_of_a_card_and_of_a_suspended_one(client):
    out = post_batch(client, [basic("pregunta <b>x</b>", "risposta")])
    cid = out["results"][0]["card_ids"][0]
    r = client.get(f"/api/cards/{cid}/preview")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["suspended"] is False and card["flag"] == 0
    assert "pregunta" in card["question_html"] and "risposta" in card["answer_html"]
    assert card["deck_name"] == "Spagnolo::Verbi" and card["deck_id"] == client.deck_id
    assert card["card_class"].startswith("card") and ".card" in card["css"]
    assert "autoplay" not in card
    # una carta sospesa si può vedere lo stesso
    with client.app.state.manager.use() as col:
        col.sched.suspend_cards([cid])
    assert client.get(f"/api/cards/{cid}/preview").json()["suspended"] is True
    assert client.get("/api/cards/1/preview").status_code == 404


# ---- mazzi ---------------------------------------------------------------------------


def test_create_deck_is_idempotent(client):
    r = client.post("/api/hub/decks", json={"name": "Storia::Antica"})
    assert r.status_code == 200
    first = r.json()
    assert first["created"] is True and first["name"] == "Storia::Antica"
    again = client.post("/api/hub/decks", json={"name": "Storia::Antica"}).json()
    assert again == {**first, "created": False, "operation_id": None}
    assert client.post("/api/hub/decks", json={"name": "Spagnolo::Verbi"}).json()["id"] == client.deck_id
    assert client.post("/api/hub/decks", json={"name": "a::::b"}).status_code == 422


# ---- spostare, cancellare, tag -------------------------------------------------------


def test_move_note(client):
    nid = client.get("/api/search/notes?q=ser").json()["notes"][0]["id"]
    new = client.post("/api/hub/decks", json={"name": "Altro"}).json()["id"]
    r = client.post(f"/api/notes/{nid}/move", json={"deck_id": new})
    assert r.status_code == 200 and r.json()["id"] == nid
    assert client.get("/api/search/notes?q=ser").json()["notes"][0]["deck_name"] == "Altro"
    assert client.post(f"/api/notes/{nid}/move", json={"deck_id": 12345}).status_code == 404
    assert client.post("/api/notes/1/move", json={"deck_id": new}).status_code == 404


def test_delete_note(client):
    nid = client.get("/api/search/notes?q=ser").json()["notes"][0]["id"]
    assert client.delete(f"/api/notes/{nid}").status_code == 204
    assert client.get(f"/api/notes/{nid}").status_code == 404
    assert client.delete(f"/api/notes/{nid}").status_code == 404
    assert note_count(client) == 2


def test_bulk_tags(client):
    ids = [n["id"] for n in client.get("/api/search/notes?q=deck:Spagnolo*").json()["notes"]]
    r = client.post("/api/notes/tags", json={"note_ids": ids + [1], "add": ["uno", "due"]})
    assert r.json() == {"updated": 3}
    r = client.post("/api/notes/tags", json={"note_ids": ids, "add": ["tre"], "remove": ["uno"]})
    assert r.json() == {"updated": 3}
    assert set(get_note(client, ids[0])["tags"]) == {"due", "tre"}
    # niente da cambiare = nessuna nota aggiornata
    assert client.post("/api/notes/tags", json={"note_ids": ids, "add": ["tre"]}).json() == {"updated": 0}
    assert client.post("/api/notes/tags", json={"note_ids": []}).status_code == 422
    # un'unica voce di undo anche con add e remove insieme
    client.post("/api/notes/tags", json={"note_ids": ids, "add": ["x"], "remove": ["due"]})
    with client.app.state.manager.use() as col:
        col.undo()
    assert set(get_note(client, ids[0])["tags"]) == {"due", "tre"}


@pytest.mark.parametrize("tags", [["a b"], ["  "]])
def test_bulk_tags_with_spaces(client, tags):
    ids = [client.get("/api/search/notes?q=ser").json()["notes"][0]["id"]]
    out = client.post("/api/notes/tags", json={"note_ids": ids, "add": tags}).json()
    assert out["updated"] == (1 if tags == ["a b"] else 0)
