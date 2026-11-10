"""Bozze e revisione: un token con `review` non aggira l'approvazione, le carte nuove di una
bozza restano sospese, approva/scarta solo ciò che l'utente ha visto, tag riservati, limiti."""

import pytest

from .test_hub import BATCH, add_tag_directly, basic, card_queues, get_note, post_batch

CLOZE = {"deck": "Spagnolo::Verbi", "notetype": "Cloze"}


def cloze(text, **extra):
    return {**CLOZE, "fields": {"Text": text}, **extra}


def approve(client, ids, **extra):
    r = client.post("/api/hub/drafts/approve", json={"note_ids": ids, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def discard(client, ids, **extra):
    r = client.post("/api/hub/drafts/discard", json={"note_ids": ids, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def is_draft(client, nid):
    return "hub::bozza" in get_note(client, nid)["tags"]


def age(client, nid, seconds=100):
    """Fa sembrare la nota modificata `seconds` fa: `mod` ha la risoluzione del secondo e un
    test veloce modificherebbe la nota nello stesso secondo in cui l'ha creata."""
    with client.app.state.manager.use() as col:
        col.db.execute("update notes set mod = mod - ? where id = ?", seconds, nid)


def listed(client, nid):
    notes = client.get("/api/hub/drafts?limit=200").json()["notes"]
    return next(n for n in notes if n["id"] == nid)


# ---- 1. un token con review non aggira l'approvazione --------------------------------------


def test_review_token_resending_an_approved_note_puts_it_back_in_draft(client, make_token):
    headers, _ = make_token("hermes", review=True)
    nid = post_batch(client, [basic("a", "uno", external_id="e1")], headers=headers)["results"][0]["note_id"]
    assert approve(client, [nid])["approved"] == 1
    assert not is_draft(client, nid) and card_queues(client, nid) == [0]

    # lo stesso contenuto non cambia niente: la nota resta approvata
    again = post_batch(client, [basic("a", "uno", external_id="e1")], headers=headers)
    assert again["results"][0]["status"] == "unchanged"
    assert not is_draft(client, nid) and card_queues(client, nid) == [0]

    # un contenuto diverso la rimette in bozza, con le carte sospese
    changed = post_batch(client, [basic("a", "DUE", external_id="e1")], headers=headers)
    assert changed["results"][0]["status"] == "updated"
    note = get_note(client, nid)
    assert note["fields"]["Back"] == "DUE" and "hub::bozza" in note["tags"]
    assert card_queues(client, nid) == [-1]
    assert client.get("/api/hub/summary").json() == {"drafts": 1}


def test_review_token_with_only_new_tags_also_redrafts(client, make_token):
    headers, _ = make_token("hermes", review=True)
    nid = post_batch(client, [basic("a", external_id="e1")], headers=headers)["results"][0]["note_id"]
    approve(client, [nid])
    post_batch(client, [basic("a", external_id="e1", tags=["nuovo"])], headers=headers)
    assert is_draft(client, nid)


def test_token_without_review_does_not_change_the_state(client, make_token):
    headers, _ = make_token("script", review=False)
    nid = post_batch(client, [basic("a", "uno", external_id="e1")], headers=headers)["results"][0]["note_id"]
    post_batch(client, [basic("a", "DUE", external_id="e1")], headers=headers)
    assert get_note(client, nid)["fields"]["Back"] == "DUE"
    assert not is_draft(client, nid) and card_queues(client, nid) == [0]


def test_patch_by_a_review_token_redrafts_an_approved_note(client, make_token):
    headers, _ = make_token("hermes", review=True)
    nid = post_batch(client, [basic("a", "uno")], headers=headers)["results"][0]["note_id"]
    approve(client, [nid])
    # una PATCH che non cambia niente lascia la nota com'è
    r = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "uno"}}, headers=headers)
    assert r.status_code == 200 and "hub::bozza" not in r.json()["tags"]
    r = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "DUE"}}, headers=headers)
    assert r.status_code == 200 and "hub::bozza" in r.json()["tags"]
    assert card_queues(client, nid) == [-1]


def test_patch_by_the_session_never_redrafts(client, make_token):
    headers, _ = make_token("hermes", review=True)
    nid = post_batch(client, [basic("a", "uno")], headers=headers)["results"][0]["note_id"]
    approve(client, [nid])
    r = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "mia modifica"}})
    assert r.status_code == 200 and "hub::bozza" not in r.json()["tags"]
    assert card_queues(client, nid) == [0]


# ---- 2. le carte nuove di una bozza cloze restano sospese ----------------------------------


def test_new_cloze_cards_of_a_draft_stay_suspended(client, make_token):
    headers, _ = make_token("hermes", review=True)
    out = post_batch(client, [cloze("{{c1::Roma}} è in Italia", external_id="c1")], headers=headers)
    nid = out["results"][0]["note_id"]
    assert card_queues(client, nid) == [-1]

    # aggiornamento da token (stesso external_id): la carta c2 nuova non entra nello studio
    again = post_batch(client, [cloze("{{c1::Roma}} è in {{c2::Italia}}", external_id="c1")], headers=headers)
    assert again["results"][0]["status"] == "updated" and len(again["results"][0]["card_ids"]) == 2
    assert card_queues(client, nid) == [-1, -1]

    # PATCH da token e PATCH della sessione (l'Inbox): idem
    for who in (headers, None):
        text = "{{c1::Roma}} {{c2::è}} in {{c3::Italia}}" if who else "{{c1::Roma}} {{c2::è}} {{c3::in}} {{c4::Italia}}"
        r = client.patch(f"/api/notes/{nid}", json={"fields": {"Text": text}}, headers=who)
        assert r.status_code == 200, r.text
        assert set(card_queues(client, nid)) == {-1}
    assert len(card_queues(client, nid)) == 4


def test_cloze_cards_of_a_normal_note_are_not_suspended(client):
    nid = post_batch(client, [cloze("{{c1::a}}")])["results"][0]["note_id"]
    client.patch(f"/api/notes/{nid}", json={"fields": {"Text": "{{c1::a}} {{c2::b}}"}})
    assert card_queues(client, nid) == [0, 0]


def test_a_token_updating_its_own_draft_without_review_suspends_new_cards(client, make_token):
    headers, _ = make_token("script", review=False)
    nid = post_batch(client, [cloze("{{c1::a}}", external_id="x")], headers=headers, draft=True)["results"][0]["note_id"]
    post_batch(client, [cloze("{{c1::a}} {{c2::b}}", external_id="x")], headers=headers)
    assert card_queues(client, nid) == [-1, -1]


# ---- 4. approvare/scartare solo ciò che l'utente ha visto -----------------------------------


def make_drafts(client, make_token, n=2):
    headers, _ = make_token("claude", review=True)
    out = post_batch(client, [basic(f"d{i}", external_id=f"d{i}") for i in range(n)], headers=headers)
    ids = [r["note_id"] for r in out["results"]]
    for i in ids:
        age(client, i)
    return headers, ids


def test_drafts_list_the_modified_time(client, make_token):
    _, (nid, _) = make_drafts(client, make_token)
    modified = listed(client, nid)["modified"]
    with client.app.state.manager.use() as col:
        assert modified == col.get_note(nid).mod
    assert modified > 0


def test_approve_skips_a_draft_changed_after_it_was_seen(client, make_token):
    headers, (a, b) = make_drafts(client, make_token)
    seen = {a: listed(client, a)["modified"], b: listed(client, b)["modified"]}
    # l'agente aggiorna la bozza `a` dopo che l'utente l'ha vista
    post_batch(client, [basic("d0", "CAMBIATA", external_id="d0")], headers=headers)
    out = approve(client, [a, b], expected_mod={str(k): v for k, v in seen.items()})
    assert out == {"approved": 1, "skipped_ids": [a]}
    assert is_draft(client, a) and card_queues(client, a) == [-1]
    assert not is_draft(client, b) and card_queues(client, b) == [0]
    # rivista la nuova versione, si può approvare
    fresh = listed(client, a)["modified"]
    assert approve(client, [a], expected_mod={a: fresh}) == {"approved": 1, "skipped_ids": []}


def test_discard_skips_a_draft_changed_after_it_was_seen(client, make_token):
    headers, (a, b) = make_drafts(client, make_token)
    seen = {a: listed(client, a)["modified"], b: listed(client, b)["modified"]}
    post_batch(client, [basic("d0", "CAMBIATA", external_id="d0")], headers=headers)
    out = discard(client, [a, b], expected_mod=seen)
    assert out == {"discarded": 1, "skipped_ids": [a]}
    assert client.get(f"/api/notes/{a}").status_code == 200
    assert client.get(f"/api/notes/{b}").status_code == 404


def test_without_expected_mod_the_behaviour_is_unchanged(client, make_token):
    headers, (a, b) = make_drafts(client, make_token)
    post_batch(client, [basic("d0", "CAMBIATA", external_id="d0")], headers=headers)
    assert approve(client, [a, b]) == {"approved": 2, "skipped_ids": []}


def test_expected_mod_only_for_some_notes(client, make_token):
    headers, (a, b) = make_drafts(client, make_token)
    post_batch(client, [basic("d1", "CAMBIATA", external_id="d1")], headers=headers)
    # per `b` non si dice cosa si è visto: si approva comunque
    out = approve(client, [a, b], expected_mod={a: listed(client, a)["modified"]})
    assert out == {"approved": 2, "skipped_ids": []}


def test_notes_that_are_not_drafts_go_in_skipped_ids(client, make_token):
    _, (a, _) = make_drafts(client, make_token)
    normal = client.get("/api/search/notes?q=ser").json()["notes"][0]["id"]
    assert approve(client, [a, a, normal, 12345]) == {"approved": 1, "skipped_ids": [normal, 12345]}
    assert approve(client, [a]) == {"approved": 0, "skipped_ids": [a]}  # già approvata


# ---- 5. scartare solo bozze vere --------------------------------------------------------------


def test_discard_never_deletes_a_note_with_reviews(client):
    # tre note "bozza" per il solo tag, come se il tag arrivasse da Anki desktop o da un altro dispositivo
    ids = [post_batch(client, [basic(f"v{i}")])["results"][0]["note_id"] for i in range(3)]
    for nid in ids:
        add_tag_directly(client, nid, "hub::bozza")
    with client.app.state.manager.use() as col:
        # 0: carta attiva; 1: sospesa ma già ripassata (type/reps); 2: sospesa, con una riga in revlog
        cards = [col.get_note(n).card_ids()[0] for n in ids]
        col.sched.suspend_cards(cards[1:])
        col.db.execute("update cards set reps = 3, type = 2 where id = ?", cards[1])
        col.db.execute(
            "insert into revlog values (?, ?, -1, 3, 1, 0, 2500, 3000, 1)", 1_700_000_000_000, cards[2]
        )
    assert discard(client, ids) == {"discarded": 0, "skipped_ids": ids}
    for nid in ids:
        assert client.get(f"/api/notes/{nid}").status_code == 200


def test_discard_deletes_an_untouched_draft(client, make_token):
    _, (a, b) = make_drafts(client, make_token)
    assert discard(client, [a, b]) == {"discarded": 2, "skipped_ids": []}


def test_a_redrafted_note_that_was_studied_cannot_be_discarded(client, make_token):
    headers, _ = make_token("hermes", review=True)
    nid = post_batch(client, [basic("a", "uno", external_id="e")], headers=headers)["results"][0]["note_id"]
    approve(client, [nid])
    with client.app.state.manager.use() as col:
        cid = col.get_note(nid).card_ids()[0]
        col.db.execute("update cards set reps = 2, type = 2 where id = ?", cid)
    post_batch(client, [basic("a", "DUE", external_id="e")], headers=headers)  # di nuovo bozza
    assert is_draft(client, nid)
    assert discard(client, [nid]) == {"discarded": 0, "skipped_ids": [nid]}


# ---- 6. tag riservati ------------------------------------------------------------------------


@pytest.fixture
def draft_note(client, make_token):
    headers, _ = make_token("claude", review=True)
    nid = post_batch(client, [basic("t", external_id="e")], headers=headers)["results"][0]["note_id"]
    return nid


@pytest.mark.parametrize(
    "body",
    [
        {"remove": ["hub::bozza"]},
        {"remove": ["HUB::Bozza"]},
        {"remove": ["  hub::bozza  "]},
        {"remove": ["hub"]},  # in Anki togliere il genitore toglie anche i figli
        {"remove": ["Agent"]},
        {"remove": ["ext"]},
        {"remove": ["agent::claude"]},
        {"remove": ["ext::E"]},
        {"add": ["hub::bozza"]},
        {"add": ["Hub::Altro"]},
        {"add": ["agent::falso"]},
        {"add": ["EXT::x"]},
        {"add": ["ok", "agent::falso"]},
    ],
)
def test_bulk_tags_cannot_touch_reserved_tags(client, draft_note, body):
    before = set(get_note(client, draft_note)["tags"])
    r = client.post("/api/notes/tags", json={"note_ids": [draft_note], **body})
    assert r.status_code == 422, r.text
    assert "hub::" in r.json()["detail"]
    assert set(get_note(client, draft_note)["tags"]) == before  # niente è cambiato
    assert card_queues(client, draft_note) == [-1]


def test_bulk_tags_still_work_for_normal_tags(client, draft_note):
    r = client.post("/api/notes/tags", json={"note_ids": [draft_note], "add": ["verbi", "hubble"], "remove": ["agentile"]})
    assert r.status_code == 200 and r.json() == {"updated": 1}
    assert {"hub::bozza", "agent::claude", "ext::e", "verbi", "hubble"} <= set(get_note(client, draft_note)["tags"])


@pytest.mark.parametrize(
    "tags",
    [
        ["agent::claude", "ext::e"],  # tolto hub::bozza
        ["hub::bozza", "ext::e"],  # tolta la provenienza
        ["hub::bozza", "agent::claude"],  # tolto l'external_id
        ["hub::bozza", "agent::claude", "ext::e", "agent::altro"],
        ["hub::bozza", "agent::claude", "ext::e", "ext::altro"],
        ["hub::bozza", "agent::claude", "ext::e", "hub::approvata"],
        [],
    ],
)
def test_patch_by_the_session_cannot_change_reserved_tags(client, draft_note, tags):
    before = set(get_note(client, draft_note)["tags"])
    r = client.patch(f"/api/notes/{draft_note}", json={"tags": tags})
    assert r.status_code == 422, r.text
    assert set(get_note(client, draft_note)["tags"]) == before


def test_patch_keeps_working_when_the_reserved_tags_come_back_unchanged(client, draft_note):
    # la PWA rimanda i tag che la nota ha già, anche con maiuscole o spazi diversi
    r = client.patch(
        f"/api/notes/{draft_note}",
        json={"tags": ["Hub::Bozza", " agent::claude ", "EXT::e", "mio"]},
    )
    assert r.status_code == 200, r.text
    assert "mio" in r.json()["tags"] and "hub::bozza" in [t.lower() for t in r.json()["tags"]]
    # e un PATCH che non tocca i tag va sempre
    assert client.patch(f"/api/notes/{draft_note}", json={"fields": {"Back": "x"}}).status_code == 200


# ---- 10. external_id, glob, tetti ------------------------------------------------------------


@pytest.mark.parametrize("bad", ["con spazio", "a*b", 'a"b', "a\\b", "a/b", "", "x" * 201, "è", "a\nb", "a%b"])
def test_external_id_pattern(client, bad):
    r = client.post(BATCH, json={"notes": [basic("x", external_id=bad)]})
    assert r.status_code == 422, bad


@pytest.mark.parametrize("good", ["a", "libro-cap3.hablar_1:x", "A" * 200, "x::y"])
def test_external_id_pattern_accepts(client, good):
    assert post_batch(client, [basic("x", external_id=good)])["created"] == 1


def test_external_id_underscore_is_not_a_wildcard(client, make_token):
    headers, _ = make_token("claude")
    other = post_batch(client, [basic("uno", external_id="axb")], headers=headers)["results"][0]["note_id"]
    out = post_batch(client, [basic("due", external_id="a_b")], headers=headers)["results"][0]
    assert out["status"] == "created" and out["note_id"] != other
    assert get_note(client, other)["fields"]["Front"] == "uno"
    # e il suo id lo ritrova: stesso id → nessun duplicato
    again = post_batch(client, [basic("due", external_id="a_b")], headers=headers)["results"][0]
    assert again["status"] == "unchanged" and again["note_id"] == out["note_id"]


def test_external_id_does_not_match_children_or_prefixes(client):
    child = post_batch(client, [basic("uno", external_id="x::y")])["results"][0]["note_id"]
    out = post_batch(client, [basic("due", external_id="x")])["results"][0]
    assert out["status"] == "created" and out["note_id"] != child


def test_a_field_over_the_limit_is_a_422_and_writes_nothing(client):
    big = "x" * (200 * 1024 + 1)
    r = client.post(BATCH, json={"notes": [basic("ok"), basic("grosso", big)]})
    assert r.status_code == 422 and "campo «Back»" in r.json()["detail"] and "200 KB" in r.json()["detail"]
    assert client.get("/api/search/notes?q=ok").json()["total"] == 0
    # esattamente al limite passa
    assert post_batch(client, [basic("limite", "x" * (200 * 1024))])["created"] == 1


def test_a_batch_over_the_total_limit_is_a_422(client):
    # 11 campi da 190 KB sono ~2,04 MB: ognuno è sotto il tetto del campo, il totale no
    notes = [basic(f"n{i}", "x" * (190 * 1024)) for i in range(11)]
    r = client.post(BATCH, json={"notes": notes})
    assert r.status_code == 422 and "2 MB" in r.json()["detail"]
    assert client.get("/api/search/notes?q=n1").json()["total"] == 0
    # anche in dry_run: l'esito è lo stesso della scrittura vera
    assert client.post(BATCH, json={"notes": notes, "dry_run": True}).status_code == 422
    assert post_batch(client, notes[:10])["created"] == 10


def test_patch_by_a_token_has_the_field_limit_too(client, make_token):
    headers, _ = make_token("claude")
    nid = post_batch(client, [basic("a")], headers=headers)["results"][0]["note_id"]
    r = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "x" * (200 * 1024 + 1)}}, headers=headers)
    assert r.status_code == 422 and "200 KB" in r.json()["detail"]


def test_drafts_limit_is_capped_at_200(client):
    assert client.get("/api/hub/drafts?limit=200").status_code == 200
    assert client.get("/api/hub/drafts?limit=201").status_code == 422
    assert client.get("/api/hub/drafts?limit=0").status_code == 422
