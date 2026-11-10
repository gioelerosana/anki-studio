"""L'«Annulla» dello studio annulla solo risposte e azioni dello studio, mai le operazioni
di altri (agenti, Inbox, selezione del mazzo): sotto c'è una sola pila di undo, condivisa."""

from .conftest import note_count
from .test_hub import basic, get_note, post_batch


def study(client):
    return client.get(f"/api/decks/{client.deck_id}/study").json()


def answer(client, rating=3):
    card = study(client)["card"]
    r = client.post(
        f"/api/decks/{client.deck_id}/study/answer",
        json={"card_id": card["card_id"], "rating": rating, "time_taken_ms": 1000},
    )
    assert r.status_code == 200, r.text
    return card, r.json()


def undo(client):
    return client.post(f"/api/decks/{client.deck_id}/study/undo")


def test_undo_is_offered_after_an_answer_and_undoes_it(client):
    card, state = answer(client)
    assert state["undo_label"]
    r = undo(client)
    assert r.status_code == 200 and r.json()["card"]["card_id"] == card["card_id"]
    assert r.json()["undo_label"] is None  # sotto non c'è niente dello studio
    assert undo(client).status_code == 409


def test_two_answers_can_be_undone_one_after_the_other(client):
    first, _ = answer(client)
    second, state = answer(client)
    assert state["undo_label"]
    r = undo(client)
    assert r.json()["card"]["card_id"] == second["card_id"] and r.json()["undo_label"]
    r = undo(client)
    assert r.json()["card"]["card_id"] == first["card_id"] and r.json()["undo_label"] is None
    assert undo(client).status_code == 409


def test_an_agent_update_after_an_answer_is_not_offered_and_not_undone(client, make_token):
    headers, _ = make_token("hermes")
    nid = post_batch(client, [basic("zz", "uno")], headers=headers)["results"][0]["note_id"]
    answer(client)
    assert client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "DUE"}}, headers=headers).status_code == 200
    # l'ultima operazione è la PATCH ("Update Note"): lo studio non la propone
    assert study(client)["undo_label"] is None
    assert undo(client).status_code == 409
    assert get_note(client, nid)["fields"]["Back"] == "DUE"


def test_an_agent_batch_between_two_answers_hides_the_older_answer(client, make_token):
    headers, _ = make_token("hermes")
    first, _ = answer(client)
    post_batch(client, [basic("nuova")], headers=headers)
    second, state = answer(client)
    assert state["undo_label"]
    before = note_count(client)
    assert undo(client).json()["card"]["card_id"] == second["card_id"]
    # sotto c'è la batch dell'agente: non si offre e non si annulla da qui
    assert study(client)["undo_label"] is None
    assert undo(client).status_code == 409
    assert note_count(client) == before
    assert first["card_id"] != second["card_id"]


def test_the_answer_after_an_agent_operation_undoes_only_itself(client, make_token):
    headers, _ = make_token("hermes")
    post_batch(client, [basic("prima")], headers=headers)
    before = note_count(client)
    card, state = answer(client)
    assert state["undo_label"]
    assert undo(client).json()["card"]["card_id"] == card["card_id"]
    assert note_count(client) == before  # la batch dell'agente resta
    assert undo(client).status_code == 409


def test_approving_or_editing_a_draft_is_not_offered(client, make_token):
    headers, _ = make_token("hermes", review=True)
    nid = post_batch(client, [basic("bozza")], headers=headers)["results"][0]["note_id"]
    answer(client)
    assert client.post("/api/hub/drafts/approve", json={"note_ids": [nid]}).status_code == 200
    assert study(client)["undo_label"] is None
    # nemmeno la risospensione delle carte di una bozza modificata da un token con review
    answer(client)
    client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "x"}}, headers=headers)
    assert study(client)["undo_label"] is None
    assert undo(client).status_code == 409
    assert client.get("/api/hub/summary").json() == {"drafts": 1}


def test_study_actions_are_undoable_from_study(client):
    did = client.deck_id
    card = study(client)["card"]
    r = client.post(f"/api/cards/{card['card_id']}/suspend", params={"deck_id": did})
    assert r.json()["undo_label"]
    r = undo(client)
    assert r.json()["card"]["card_id"] == card["card_id"]

    r = client.post(f"/api/cards/{card['card_id']}/bury", params={"deck_id": did})
    assert r.json()["undo_label"]
    assert undo(client).json()["card"]["card_id"] == card["card_id"]

    assert client.post(f"/api/cards/{card['card_id']}/flag", json={"flag": 2}).status_code == 204
    assert study(client)["undo_label"]
    undo(client)
    assert study(client)["card"]["flag"] == 0


def test_a_study_action_without_deck_id_is_tracked_too(client, make_token):
    headers, _ = make_token("hermes")
    card = study(client)["card"]
    assert client.post(f"/api/cards/{card['card_id']}/suspend").status_code == 204
    assert study(client)["undo_label"]
    post_batch(client, [basic("x")], headers=headers)
    assert study(client)["undo_label"] is None


def test_selecting_another_deck_after_an_answer_offers_nothing(client):
    answer(client)
    other = next(d for d in client.get("/api/decks").json() if d["name"] == "Spagnolo")
    s = client.get(f"/api/decks/{other['id']}/study").json()
    assert s["undo_label"] is None
    assert client.post(f"/api/decks/{other['id']}/study/undo").status_code == 409


def test_nothing_is_offered_on_a_fresh_start(client, make_token):
    # un'operazione di un agente prima di qualsiasi risposta non è mai annullabile dallo studio
    headers, _ = make_token("hermes")
    post_batch(client, [basic("x")], headers=headers)
    assert study(client)["undo_label"] is None
    assert undo(client).status_code == 409

