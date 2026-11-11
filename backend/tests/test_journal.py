"""Diario delle operazioni degli agenti e annullamento (app/journal.py, docs/PIANO-HUB.md):
registrazione, undo di note e mazzi, salti, `partial`, permessi, persistenza, limiti, MCP, log."""

import json
import logging
import stat

import pytest
from fastapi.testclient import TestClient

from app.journal import Actor, Journal, item_deck
from app.main import create_app

from .conftest import note_count
from .test_hub import basic, get_note, post_batch
from .test_mcp import call, mcp_client, note_args, text_of, tokens  # noqa: F401

OPS = "/api/hub/operations"


def operations(client, headers=None, limit=None):
    url = OPS if limit is None else f"{OPS}?limit={limit}"
    r = client.get(url, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["operations"]


def undo(client, op_id, headers=None):
    return client.post(f"{OPS}/{op_id}/undo", headers=headers)


def create(client, headers=None, *fronts, **opts):
    """Una batch di note Basic; restituisce (operation_id, [note_id])."""
    out = post_batch(client, [basic(f) for f in fronts], headers=headers, **opts)
    return out["operation_id"], [r["note_id"] for r in out["results"]]


def cards_of(client, nid):
    with client.app.state.manager.use() as col:
        return [int(c) for c in col.get_note(nid).card_ids()]


def exists(client, nid):
    return client.get(f"/api/notes/{nid}").status_code == 200


def edit_directly(client, nid, **fields):
    """Come se l'utente modificasse la nota da Anki desktop: salta le nostre rotte, quindi anche
    il diario. Sullo stesso secondo `mod` può non cambiare: conta l'impronta del contenuto."""
    with client.app.state.manager.use() as col:
        note = col.get_note(nid)
        for k, v in fields.items():
            note[k] = v
        col.update_note(note)


# ---- registrazione ---------------------------------------------------------------------------


def test_a_batch_is_recorded_with_agent_summary_and_count(client, make_token):
    headers, _ = make_token("Hermes Agent")
    op, ids = create(client, headers, "uno", "due", "tre")
    assert op and len(ids) == 3
    [entry] = operations(client)
    assert entry == {
        "id": op,
        "created_at": entry["created_at"],
        "agent": "hermes-agent",
        "kind": "add_notes",
        "summary": "3 note create in Spagnolo::Verbi",
        "note_count": 3,
        "status": "applied",
        "undone_at": None,
    }
    assert abs(entry["created_at"] - __import__("time").time()) < 30


def test_the_operation_id_is_in_the_batch_result_and_distinct_per_batch(client):
    first, _ = create(client, None, "a")
    second, _ = create(client, None, "b")
    assert first and second and first != second
    assert [o["id"] for o in operations(client)] == [second, first]  # dalla più recente


def test_nothing_real_nothing_recorded(client, make_token):
    headers, _ = make_token("claude")
    # dry_run
    out = post_batch(client, [basic("x")], headers=headers, dry_run=True)
    assert out["operation_id"] is None
    # errori (mazzo che non esiste, campo sbagliato)
    out = post_batch(
        client,
        [basic("y", deck="Boh"), {"deck": "Spagnolo::Verbi", "notetype": "Basic", "fields": {"Nope": "x"}}],
        headers=headers,
    )
    assert out["operation_id"] is None and out["errors"] == 2
    # duplicato di una nota che c'è già
    dup = post_batch(client, [basic('ser <img src="pic.png">')], headers=headers)
    assert dup["duplicates"] == 1 and dup["operation_id"] is None
    # unchanged
    create_op, _ = create(client, headers, "z")
    again = post_batch(client, [basic("z", external_id="e")], headers=headers)
    assert again["operation_id"]
    assert post_batch(client, [basic("z", external_id="e")], headers=headers)["operation_id"] is None
    assert len(operations(client)) == 2  # solo la creazione di "z" e quella con external_id


def test_updating_through_external_id_is_an_update_operation_that_restores_previous_state(client, make_token):
    headers, _ = make_token("claude")
    first = post_batch(client, [basic("hablar", "parlare", external_id="h", tags=["uno"])], headers=headers)
    nid = first["results"][0]["note_id"]
    out = post_batch(client, [basic("hablar", "dire", external_id="h", tags=["due"])], headers=headers)
    assert out["updated"] == 1 and out["operation_id"]
    entry = operations(client)[0]
    assert entry["kind"] == "add_notes" and entry["summary"] == "1 nota aggiornata" and entry["note_count"] == 1
    assert set(get_note(client, nid)["tags"]) == {"uno", "due", "agent::claude", "ext::h"}

    r = undo(client, out["operation_id"], headers)
    assert r.status_code == 200
    assert r.json() == {
        "operation_id": out["operation_id"],
        "status": "undone",
        "restored": 1,
        "deleted": 0,
        "skipped": [],
    }
    note = get_note(client, nid)
    assert note["fields"]["Back"] == "parlare"
    # tag ESATTI di prima, provenienza e id dell'invio compresi
    assert set(note["tags"]) == {"uno", "agent::claude", "ext::h"}


def test_legacy_token_is_recorded_as_admin(client):
    op, _ = create(client, None, "dal token legacy")
    assert operations(client)[0]["agent"] == "admin" and operations(client)[0]["id"] == op


def test_session_is_recorded_as_sessione(seeded):
    settings, _ = seeded
    settings = settings.model_copy(update={"anki_dev_login": True, "anki_api_token": None})
    with TestClient(create_app(settings), base_url="https://anki.test") as c:
        c.get("/api/auth/login", follow_redirects=False)
        sop, [nid] = create(c, None, "dalla sessione")
        [entry] = operations(c)
        assert entry["id"] == sop and entry["agent"] == "sessione"
        # la sessione modifica una nota dalla PWA (PATCH): anche quella è nel diario
        patch = c.patch(f"/api/notes/{nid}", json={"fields": {"Back": "x"}}).json()
        assert [o["agent"] for o in operations(c)] == ["sessione", "sessione"]
        assert undo(c, patch["operation_id"]).status_code == 200


def test_summary_mentions_decks_and_created_decks(client):
    out = post_batch(
        client,
        [basic("uno", deck="Nuovo::Sotto"), basic("due", deck="Nuovo::Sotto"), basic("tre", deck="Altro")],
        create_missing_decks=True,
    )
    entry = operations(client)[0]
    assert entry["summary"] == "3 note create in 2 mazzi (3 mazzi creati)"
    assert entry["note_count"] == 3 and entry["id"] == out["operation_id"]
    # una sola nota in un solo mazzo, senza mazzi nuovi: il nome del mazzo
    create(client, None, "quattro")
    assert operations(client)[0]["summary"] == "1 nota creata in Spagnolo::Verbi"


def test_create_deck_is_recorded_only_when_it_creates_something(client, make_token):
    headers, _ = make_token("claude")
    r = client.post("/api/hub/decks", json={"name": "Lingue::Francese"}, headers=headers)
    assert r.json()["created"] is True and r.json()["operation_id"]
    again = client.post("/api/hub/decks", json={"name": "Lingue::Francese"}, headers=headers).json()
    assert again["created"] is False and again["operation_id"] is None
    ops = operations(client)
    assert len(ops) == 1
    assert ops[0]["kind"] == "create_deck" and ops[0]["note_count"] == 0
    assert ops[0]["summary"] == "2 mazzi creati: Lingue, Lingue::Francese"


def test_patch_records_an_update_and_returns_operation_id(client, make_token):
    headers, _ = make_token("claude")
    _, [nid] = create(client, headers, "m1")
    r = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "nuovo"}, "tags": ["x"]}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["operation_id"] and body["fields"]["Back"] == "nuovo"
    entry = next(o for o in operations(client) if o["id"] == body["operation_id"])
    assert entry["kind"] == "update_note" and entry["note_count"] == 1
    assert entry["summary"] == f"Nota {nid} aggiornata (Back, tag)"
    # una modifica che non cambia niente non si registra, e il campo è null
    same = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "nuovo"}}, headers=headers)
    assert same.status_code == 200 and same.json()["operation_id"] is None
    assert len(operations(client)) == 2
    # le altre risposte non portano l'id
    assert client.get(f"/api/notes/{nid}").json()["operation_id"] is None


def test_limit_parameter_and_validation(client):
    for i in range(5):
        create(client, None, f"n{i}")
    assert len(operations(client)) == 5
    assert len(operations(client, limit=2)) == 2
    assert client.get(f"{OPS}?limit=0").status_code == 422
    assert client.get(f"{OPS}?limit=201").status_code == 422
    assert len(operations(client, limit=200)) == 5


# ---- annullamento: note create ---------------------------------------------------------------


def test_undo_deletes_created_notes_and_marks_the_operation(client, make_token):
    headers, _ = make_token("claude")
    before = note_count(client)
    op, ids = create(client, headers, "a", "b")
    r = undo(client, op, headers)
    assert r.status_code == 200
    assert r.json() == {"operation_id": op, "status": "undone", "restored": 0, "deleted": 2, "skipped": []}
    assert note_count(client) == before and not any(exists(client, i) for i in ids)
    # non è una nuova operazione: la stessa voce, ora annullata
    [entry] = operations(client)
    assert entry["id"] == op and entry["status"] == "undone" and entry["undone_at"] >= entry["created_at"]
    # già annullata: 409 con un messaggio chiaro
    again = undo(client, op, headers)
    assert again.status_code == 409 and "già annullata" in again.json()["detail"]


def test_undo_unknown_id_is_404(client):
    r = undo(client, "nonesiste")
    assert r.status_code == 404


def test_undo_skips_a_note_modified_after_the_operation_and_can_be_retried(client, make_token):
    headers, _ = make_token("claude")
    op, [a, b] = create(client, headers, "a", "b")
    edit_directly(client, b, Back="toccata dall'utente")
    r = undo(client, op, headers)
    body = r.json()
    assert body["status"] == "partial" and body["deleted"] == 1 and body["restored"] == 0
    assert body["skipped"] == [{"note_id": b, "reason": "modificata dopo l'operazione"}]
    assert not exists(client, a) and exists(client, b)
    assert operations(client)[0]["status"] == "partial" and operations(client)[0]["undone_at"] is None
    # ritentare: la nota già annullata non si rifà, quella modificata si salta ancora
    again = undo(client, op, headers)
    assert again.status_code == 200
    assert again.json()["deleted"] == 0 and again.json()["status"] == "partial"
    assert [s["note_id"] for s in again.json()["skipped"]] == [b]


def test_undo_skips_a_note_whose_tags_changed(client, make_token):
    headers, _ = make_token("claude")
    op, [nid] = create(client, headers, "a")
    client.post("/api/notes/tags", json={"note_ids": [nid], "add": ["mio"]})
    body = undo(client, op, headers).json()
    assert body["status"] == "partial" and body["skipped"][0]["reason"] == "modificata dopo l'operazione"
    assert exists(client, nid)


def test_undo_skips_a_note_that_no_longer_exists(client, make_token):
    headers, _ = make_token("claude")
    op, [nid] = create(client, headers, "a")
    assert client.delete(f"/api/notes/{nid}").status_code == 204
    body = undo(client, op, headers).json()
    assert body["status"] == "partial" and body["skipped"] == [{"note_id": nid, "reason": "la nota non esiste più"}]


def test_undo_skips_notes_with_studied_cards(client, make_token):
    headers, _ = make_token("claude")
    op, [studied, fresh] = create(client, headers, "studiata", "fresca")
    with client.app.state.manager.use() as col:
        col.db.execute("update cards set reps = 1 where nid = ?", studied)
    body = undo(client, op, headers).json()
    assert body["status"] == "partial" and body["deleted"] == 1
    assert body["skipped"] == [{"note_id": studied, "reason": "ha carte già studiate"}]
    assert exists(client, studied) and not exists(client, fresh)


def test_undo_skips_notes_with_review_history_even_if_reps_is_zero(client, make_token):
    headers, _ = make_token("claude")
    op, [nid] = create(client, headers, "storia")
    cid = cards_of(client, nid)[0]
    with client.app.state.manager.use() as col:
        col.db.execute(
            "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) values (?,?,?,?,?,?,?,?,?)",
            1_700_000_000_000, cid, -1, 3, 1, 0, 2500, 1000, 0,
        )
    body = undo(client, op, headers).json()
    assert body["status"] == "partial" and body["skipped"][0]["reason"] == "ha carte già studiate"
    assert exists(client, nid)


def test_a_failure_on_one_item_does_not_stop_the_others(client, make_token, monkeypatch):
    headers, _ = make_token("claude")
    op, [a, b, c] = create(client, headers, "a", "b", "c")
    with client.app.state.manager.use() as col:
        real = type(col).remove_notes

        def flaky(self, note_ids):
            if b in note_ids:
                raise RuntimeError("disco pieno")
            return real(self, note_ids)

        monkeypatch.setattr(type(col), "remove_notes", flaky)
    r = undo(client, op, headers)
    assert r.status_code == 200, r.text  # nessuna eccezione a metà
    body = r.json()
    assert body["deleted"] == 2 and body["status"] == "partial"
    assert body["skipped"][0]["note_id"] == b and "disco pieno" in body["skipped"][0]["reason"]
    assert not exists(client, a) and exists(client, b) and not exists(client, c)
    monkeypatch.undo()
    final = undo(client, op, headers).json()
    assert final["status"] == "undone" and final["deleted"] == 1 and not exists(client, b)


# ---- annullamento: note aggiornate -----------------------------------------------------------


def test_undo_restores_fields_and_exact_tags_of_an_updated_note(client, make_token):
    headers, _ = make_token("claude")
    created = post_batch(client, [basic("f", "uno", external_id="e1", tags=["vecchio"])], headers=headers)
    nid = created["results"][0]["note_id"]
    r = client.patch(
        f"/api/notes/{nid}", json={"fields": {"Back": "due"}, "tags": ["nuovo", "agent::finto"]}, headers=headers
    )
    op = r.json()["operation_id"]
    assert set(r.json()["tags"]) == {"nuovo", "agent::claude", "ext::e1"}
    out = undo(client, op, headers).json()
    assert out["status"] == "undone" and out["restored"] == 1 and out["deleted"] == 0
    note = get_note(client, nid)
    assert note["fields"]["Back"] == "uno"
    assert set(note["tags"]) == {"vecchio", "agent::claude", "ext::e1"}


def test_undo_of_an_update_is_skipped_when_someone_else_modified_the_note(client, make_token):
    headers, _ = make_token("claude")
    _, [nid] = create(client, headers, "x")
    op = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "agente"}}, headers=headers).json()["operation_id"]
    # l'utente (sessione/admin) la modifica dopo: l'undo non deve sovrascrivere il suo lavoro
    assert client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "utente"}}).status_code == 200
    body = undo(client, op, headers).json()
    assert body["status"] == "partial" and body["restored"] == 0
    assert body["skipped"] == [{"note_id": nid, "reason": "modificata dopo l'operazione"}]
    assert get_note(client, nid)["fields"]["Back"] == "utente"


def test_same_second_edit_is_caught_by_the_content_fingerprint(client, make_token):
    """`mod` è al secondo: una modifica nello stesso secondo non lo cambia, ma il contenuto sì."""
    headers, _ = make_token("claude")
    _, [nid] = create(client, headers, "x")
    op = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "agente"}}, headers=headers).json()["operation_id"]
    with client.app.state.manager.use() as col:
        note = col.get_note(nid)
        before_mod = note.mod
        note["Back"] = "utente"
        col.update_note(note)
        # forziamo lo stesso `mod` come se la modifica fosse nello stesso secondo
        col.db.execute("update notes set mod = ? where id = ?", before_mod, nid)
    body = undo(client, op, headers).json()
    assert body["status"] == "partial"
    assert get_note(client, nid)["fields"]["Back"] == "utente"


def test_undoing_the_update_and_then_the_creation_works(client, make_token):
    """B (aggiornamento) e poi A (creazione): il ripristino cambia `mod`, ma A deve poter ancora
    cancellare la nota."""
    headers, _ = make_token("claude")
    a, [nid] = create(client, headers, "x")
    b = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "dopo"}}, headers=headers).json()["operation_id"]
    # annullare A per prima: la nota è cambiata dopo (da B), si salta
    first = undo(client, a, headers).json()
    assert first["status"] == "partial" and exists(client, nid)
    assert undo(client, b, headers).json()["status"] == "undone"
    last = undo(client, a, headers).json()
    assert last["status"] == "undone" and last["deleted"] == 1 and not exists(client, nid)


# ---- annullamento: mazzi ---------------------------------------------------------------------


def test_undo_deletes_created_decks_deepest_first(client, make_token):
    headers, _ = make_token("claude")
    out = client.post("/api/hub/decks", json={"name": "A::B::C"}, headers=headers).json()
    body = undo(client, out["operation_id"], headers).json()
    assert body["status"] == "undone" and body["deleted"] == 3 and body["skipped"] == []
    with client.app.state.manager.use() as col:
        assert col.decks.id_for_name("A") is None and col.decks.id_for_name("A::B::C") is None


def test_undo_of_add_notes_with_new_decks_deletes_notes_then_decks(client, make_token):
    headers, _ = make_token("claude")
    out = post_batch(client, [basic("n", deck="Prova::Hub")], headers=headers, create_missing_decks=True)
    assert operations(client)[0]["summary"] == "1 nota creata in Prova::Hub (2 mazzi creati)"
    body = undo(client, out["operation_id"], headers).json()
    assert body["status"] == "undone" and body["deleted"] == 3  # nota + 2 mazzi
    with client.app.state.manager.use() as col:
        assert col.decks.id_for_name("Prova") is None


def test_undo_keeps_a_deck_that_is_not_empty_and_can_be_retried(client, make_token):
    headers, _ = make_token("claude")
    out = post_batch(client, [basic("n", deck="Nuovo")], headers=headers, create_missing_decks=True)
    # l'utente aggiunge una sua nota nel mazzo nuovo
    mine = post_batch(client, [basic("mia", deck="Nuovo")])["results"][0]["note_id"]
    body = undo(client, out["operation_id"], headers).json()
    assert body["status"] == "partial" and body["deleted"] == 1
    assert body["skipped"] == [{"note_id": None, "reason": "«Nuovo» non è vuoto"}]
    # ora la nota dell'utente se ne va (o viene spostata): il mazzo si può eliminare
    assert client.delete(f"/api/notes/{mine}").status_code == 204
    final = undo(client, out["operation_id"], headers).json()
    assert final["status"] == "undone" and final["deleted"] == 1 and final["skipped"] == []


def test_undo_keeps_a_deck_with_subdecks(client, make_token):
    headers, _ = make_token("claude")
    op = client.post("/api/hub/decks", json={"name": "Padre"}, headers=headers).json()["operation_id"]
    client.post("/api/hub/decks", json={"name": "Padre::Figlio"})  # dell'utente
    body = undo(client, op, headers).json()
    assert body["status"] == "partial" and "sottomazzi" in body["skipped"][0]["reason"]


# ---- permessi e isolamento -------------------------------------------------------------------


def test_agents_see_and_undo_only_their_own_operations(client, make_token):
    one, _ = make_token("uno")
    two, _ = make_token("due")
    op1, [n1] = create(client, one, "n1")
    op2, [n2] = create(client, two, "n2")
    opa, [na] = create(client, None, "admin")

    assert [o["id"] for o in operations(client, one)] == [op1]
    assert [o["id"] for o in operations(client, two)] == [op2]
    assert {o["id"] for o in operations(client)} == {op1, op2, opa}  # l'amministratore vede tutto

    # un id di un altro non si rivela: 404, e non cambia niente
    for headers, other in ((one, op2), (one, opa), (two, op1)):
        assert undo(client, other, headers).status_code == 404
    assert exists(client, n1) and exists(client, n2) and exists(client, na)
    assert [o["status"] for o in operations(client)] == ["applied"] * 3

    assert undo(client, op1, one).status_code == 200 and not exists(client, n1)


def test_session_and_admin_can_undo_any_operation(client, make_token):
    headers, _ = make_token("claude")
    op, [nid] = create(client, headers, "x")
    assert undo(client, op).status_code == 200  # ANKI_API_TOKEN
    assert not exists(client, nid)


def test_a_token_named_admin_cannot_touch_the_admin_operations(client, make_token):
    """Conta il flag `scoped`, non il nome: un token chiamato «admin» o «sessione» non vede le
    operazioni della sessione o del token legacy."""
    fake, _ = make_token("admin")
    op, [nid] = create(client, None, "dell'admin")
    assert operations(client, fake) == []
    assert undo(client, op, fake).status_code == 404
    assert exists(client, nid)
    mine, _ = create(client, fake, "del finto admin")
    assert [o["id"] for o in operations(client, fake)] == [mine]


def test_read_token_lists_its_own_but_cannot_undo(client, make_token):
    headers, _ = make_token("lettore", scope="read")
    assert operations(client, headers) == []
    op, [nid] = create(client, None, "x")
    assert operations(client, headers) == []  # non vede quelle altrui
    r = undo(client, op, headers)
    assert r.status_code == 403
    assert exists(client, nid) and operations(client)[0]["status"] == "applied"
    # un token write passato a read: vede ancora le proprie ma non annulla più
    w, created = make_token("scrittore")
    wop, _ = create(client, w, "mia")
    assert client.patch(f"/api/tokens/{created['id']}", json={"scope": "read"}).status_code == 200
    assert [o["id"] for o in operations(client, w)] == [wop]
    assert undo(client, wop, w).status_code == 403


def test_operations_require_authentication(client):
    assert client.get(OPS, headers={"Authorization": ""}).status_code == 401
    assert client.post(f"{OPS}/x/undo", headers={"Authorization": ""}).status_code == 401


# ---- lo studio non vede questi undo ----------------------------------------------------------


def test_undoing_an_operation_does_not_leave_an_undo_for_the_study(client, make_token):
    headers, _ = make_token("claude")
    op, _ = create(client, headers, "x")
    assert undo(client, op, headers).status_code == 200
    state = client.get(f"/api/decks/{client.deck_id}/study").json()
    assert state["undo_label"] is None
    assert client.post(f"/api/decks/{client.deck_id}/study/undo").status_code == 409


# ---- persistenza -----------------------------------------------------------------------------


def test_the_journal_survives_a_restart_and_is_private(seeded):
    settings, did = seeded
    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = "Bearer test-token-abcdefghijklmnop"
        token = c.post("/api/tokens", json={"name": "claude"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        op, [nid] = create(c, headers, "persiste")
        patch = c.patch(f"/api/notes/{nid}", json={"fields": {"Back": "x"}}, headers=headers).json()["operation_id"]
    path = settings.anki_data_dir / "agent-ops.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and not path.with_suffix(".tmp").exists()
    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = "Bearer test-token-abcdefghijklmnop"
        assert {o["id"] for o in operations(c)} == {op, patch}
        # e si può ancora annullare, anche dopo un riavvio
        assert undo(c, patch).json()["status"] == "undone"
        assert get_note(c, nid)["fields"]["Back"] == "r"
    reread = Journal(path)
    assert {o.id: o.status for o in reread._ops} == {op: "applied", patch: "undone"}


def test_the_file_has_no_media_content_and_only_text_of_changed_fields(client, make_token, seeded):
    settings, _ = seeded
    headers, _ = make_token("claude")
    post_batch(client, [basic('<img src="foto.png"> grande', "x" * 50, external_id="m")], headers=headers)
    post_batch(client, [basic('<img src="foto.png"> grande', "y" * 50, external_id="m")], headers=headers)
    raw = json.loads((settings.anki_data_dir / "agent-ops.json").read_text())
    update = raw["operations"][1]["items"][0]
    # solo il campo cambiato (Back), non tutta la nota; il nome del file media, non i suoi byte
    assert update["fields"] == {"Back": "x" * 50}
    assert "foto.png" not in json.dumps(update)


def test_a_corrupt_journal_is_set_aside_and_we_start_empty(tmp_path, caplog):
    path = tmp_path / "agent-ops.json"
    path.write_text("{non json: testo di una carta")
    caplog.set_level(logging.DEBUG)
    journal = Journal(path)
    assert journal.list() == []
    backups = list(tmp_path.glob("agent-ops.json.bak-*"))
    assert [p.read_text() for p in backups] == ["{non json: testo di una carta"]
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    assert "testo di una carta" not in caplog.text and "agent-ops.json" in caplog.text
    # si riparte: il primo record crea un file nuovo, il backup resta
    journal.record(Actor("a", True), "create_deck", "x", [item_deck(5, "X")])
    assert json.loads(path.read_text())["operations"] and len(list(tmp_path.glob("*.bak-*"))) == 1


@pytest.mark.parametrize(
    "content",
    ['{"operations": "no"}', '{"operations": [{"id": "a"}]}', "[]", '{"nope": 1}', ""],
)
def test_a_journal_of_the_wrong_shape_is_set_aside(tmp_path, content):
    path = tmp_path / "agent-ops.json"
    path.write_text(content)
    assert Journal(path).list() == []
    assert [p.read_text() for p in tmp_path.glob("agent-ops.json.bak-*")] == [content]


def test_unknown_fields_in_the_journal_are_ignored(tmp_path):
    path = tmp_path / "agent-ops.json"
    journal = Journal(path)
    op = journal.record(Actor("claude", True), "create_deck", "Mazzo creato: X", [item_deck(5, "X")])
    raw = json.loads(path.read_text())
    raw["operations"][0]["futuro"] = 1
    raw["operations"][0]["items"][0]["altro"] = 2
    path.write_text(json.dumps(raw))
    assert [o.id for o in Journal(path).list()] == [op]
    assert not list(tmp_path.glob("*.bak-*"))


def test_a_disk_error_never_breaks_the_operation(tmp_path, monkeypatch):
    path = tmp_path / "agent-ops.json"
    journal = Journal(path)
    monkeypatch.setattr("app.journal.os.open", lambda *a, **k: (_ for _ in ()).throw(OSError("pieno")))
    op = journal.record(Actor("claude", True), "create_deck", "x", [item_deck(5, "X")])
    assert op and [o.id for o in journal.list()] == [op]  # almeno in memoria


# ---- limiti ----------------------------------------------------------------------------------


def fill(journal, n, actor=Actor("claude", True)):
    return [journal.record(actor, "create_deck", f"op {i}", [item_deck(10 + i, f"D{i}")]) for i in range(n)]


def test_only_the_last_200_operations_are_kept(tmp_path):
    journal = Journal(tmp_path / "agent-ops.json")
    ids = fill(journal, 205)
    kept = [o.id for o in journal.list(limit=200)]
    assert len(kept) == 200 and kept[0] == ids[-1] and kept[-1] == ids[5]
    assert len(Journal(tmp_path / "agent-ops.json")._ops) == 200  # anche su disco


def test_operations_older_than_30_days_are_dropped(tmp_path):
    now = [1_800_000_000.0]
    journal = Journal(tmp_path / "agent-ops.json", clock=lambda: now[0])
    old = fill(journal, 2)
    now[0] += 29 * 86400
    recent = fill(journal, 1)
    assert len(journal.list()) == 3
    now[0] += 2 * 86400  # le prime due ora hanno 31 giorni
    assert [o.id for o in journal.list()] == recent
    assert old[0] not in {o.id for o in Journal(tmp_path / "agent-ops.json", clock=lambda: now[0]).list()}
    with pytest.raises(Exception):
        journal.undo(None, old[0])  # una voce dimenticata non esiste più


def test_the_file_size_is_capped_and_the_newest_operation_always_stays(tmp_path):
    journal = Journal(tmp_path / "agent-ops.json", max_bytes=2000)
    fill(journal, 30)
    ops = journal.list(limit=200)
    assert 1 <= len(ops) < 30 and ops[0].summary == "op 29"


# ---- log -------------------------------------------------------------------------------------


def test_no_secrets_or_card_text_in_the_logs(client, make_token, caplog):
    caplog.set_level(logging.DEBUG)
    headers, created = make_token("claude")
    plain = created["token"]
    secret = "TESTO-RISERVATO-DELLA-CARTA"
    op, [nid] = create(client, headers, secret)
    upd = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": secret + "-2"}}, headers=headers).json()
    undo(client, upd["operation_id"], headers)
    undo(client, op, headers)
    undo(client, op, headers)  # 409
    operations(client, headers)
    assert plain not in caplog.text and secret not in caplog.text
    assert "Operazione registrata" in caplog.text and "Operazione annullata" in caplog.text


# ---- server MCP ------------------------------------------------------------------------------


def test_mcp_add_notes_then_list_and_undo(mcp_client, tokens):  # noqa: F811
    token = tokens("claude")
    out = call(mcp_client, "add_notes", {"notes": [note_args("m1"), note_args("m2")]}, token=token)["structuredContent"]
    op = out["operation_id"]
    assert op and out["created"] == 2
    listed = call(mcp_client, "list_operations", {}, token=token)["structuredContent"]["operations"]
    assert [o["id"] for o in listed] == [op] and listed[0]["agent"] == "claude"
    assert listed[0]["summary"] == "2 note create in Spagnolo::Verbi" and listed[0]["status"] == "applied"

    r = call(mcp_client, "undo_operation", {"operation_id": op}, token=token)
    assert not r["isError"]
    assert r["structuredContent"] == {
        "operation_id": op, "status": "undone", "restored": 0, "deleted": 2, "skipped": [],
    }
    assert mcp_client.get("/api/search/notes?q=m1").json()["total"] == 0
    assert call(mcp_client, "list_operations", {}, token=token)["structuredContent"]["operations"][0]["status"] == "undone"
    twice = call(mcp_client, "undo_operation", {"operation_id": op}, token=token)
    assert twice["isError"] and "già annullata" in text_of(twice)


def test_mcp_update_note_returns_the_operation_id_and_undo_restores(mcp_client, tokens):  # noqa: F811
    token = tokens("claude")
    nid = call(mcp_client, "add_notes", {"notes": [note_args("u", "prima")]}, token=token)["structuredContent"]["results"][0]["note_id"]
    upd = call(mcp_client, "update_note", {"note_id": nid, "fields": {"Back": "dopo"}}, token=token)["structuredContent"]
    assert upd["operation_id"] and upd["fields"]["Back"] == "dopo"
    nothing = call(mcp_client, "update_note", {"note_id": nid, "fields": {"Back": "dopo"}}, token=token)["structuredContent"]
    assert nothing["operation_id"] is None
    r = call(mcp_client, "undo_operation", {"operation_id": upd["operation_id"]}, token=token)["structuredContent"]
    assert r["status"] == "undone" and r["restored"] == 1
    assert call(mcp_client, "get_note", {"note_id": nid}, token=token)["structuredContent"]["fields"]["Back"] == "prima"


def test_mcp_create_deck_returns_the_operation_id(mcp_client, tokens):  # noqa: F811
    token = tokens("claude")
    deck = call(mcp_client, "create_deck", {"name": "Mcp::Mazzo"}, token=token)["structuredContent"]
    assert deck["operation_id"]
    assert call(mcp_client, "undo_operation", {"operation_id": deck["operation_id"]}, token=token)["structuredContent"]["deleted"] == 2


def test_mcp_agents_only_see_and_undo_their_own(mcp_client, tokens):  # noqa: F811
    mine, other = tokens("mio"), tokens("altro")
    mine_op = call(mcp_client, "add_notes", {"notes": [note_args("a")]}, token=mine)["structuredContent"]["operation_id"]
    other_op = call(mcp_client, "add_notes", {"notes": [note_args("b")]}, token=other)["structuredContent"]["operation_id"]
    assert [o["id"] for o in call(mcp_client, "list_operations", {}, token=mine)["structuredContent"]["operations"]] == [mine_op]
    denied = call(mcp_client, "undo_operation", {"operation_id": other_op}, token=mine)
    assert denied["isError"] and "non trovata" in text_of(denied)
    assert mcp_client.get("/api/search/notes?q=b").json()["total"] >= 1
    # l'amministratore (ANKI_API_TOKEN) vede tutto
    admin = call(mcp_client, "list_operations", {})["structuredContent"]["operations"]
    assert {o["id"] for o in admin} == {mine_op, other_op}


def test_mcp_read_scope_lists_but_cannot_undo(mcp_client, tokens):  # noqa: F811
    reader = tokens("lettore", scope="read")
    op = call(mcp_client, "add_notes", {"notes": [note_args("z")]})["structuredContent"]["operation_id"]
    assert call(mcp_client, "list_operations", {}, token=reader)["structuredContent"]["operations"] == []
    r = call(mcp_client, "undo_operation", {"operation_id": op}, token=reader)
    assert r["isError"] and "scope «read»" in text_of(r)
    assert mcp_client.get("/api/search/notes?q=z").json()["total"] >= 1


def test_mcp_undo_skips_modified_notes_and_says_why(mcp_client, tokens):  # noqa: F811
    token = tokens("claude")
    out = call(mcp_client, "add_notes", {"notes": [note_args("s")]}, token=token)["structuredContent"]
    nid = out["results"][0]["note_id"]
    assert mcp_client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "utente"}}).status_code == 200
    r = call(mcp_client, "undo_operation", {"operation_id": out["operation_id"]}, token=token)
    assert not r["isError"]
    assert r["structuredContent"]["status"] == "partial"
    assert r["structuredContent"]["skipped"] == [{"note_id": nid, "reason": "modificata dopo l'operazione"}]


def test_mcp_undo_validates_the_id(mcp_client, tokens):  # noqa: F811
    token = tokens("claude")
    missing = call(mcp_client, "undo_operation", {"operation_id": "nonesiste"}, token=token)
    assert missing["isError"] and "non trovata" in text_of(missing)
    weird = call(mcp_client, "undo_operation", {"operation_id": "../x"}, token=token)
    assert weird["isError"]
    bad_limit = call(mcp_client, "list_operations", {"limit": 0}, token=token)
    assert bad_limit["isError"]


def test_mcp_undo_requests_a_sync_only_when_it_changes_something(mcp_client, tokens, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(mcp_client.app.state.sync, "request_soon", lambda: calls.append(1))
    token = tokens("claude")
    out = call(mcp_client, "add_notes", {"notes": [note_args("sy")]}, token=token)["structuredContent"]
    assert len(calls) == 1
    call(mcp_client, "undo_operation", {"operation_id": "nonesiste"}, token=token)
    assert len(calls) == 1
    call(mcp_client, "undo_operation", {"operation_id": out["operation_id"]}, token=token)
    assert len(calls) == 2
    call(mcp_client, "undo_operation", {"operation_id": out["operation_id"]}, token=token)  # già annullata
    assert len(calls) == 2
