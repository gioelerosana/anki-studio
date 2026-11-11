"""Sync dopo la scrittura: debounce, niente da fare se AnkiWeb non è collegato.
Nessuna rete: la sync vera è sostituita da un registratore."""

import threading
import time

from app.config import Settings
from app.sync import StoredAuth, SyncOutcome, SyncResult, SyncService

from .test_hub import basic, post_batch


def service(tmp_path, seconds, logged_in=True):
    svc = SyncService(None, tmp_path / "auth.json", after_write_seconds=seconds)  # type: ignore[arg-type]
    if logged_in:
        svc._auth = StoredAuth("u", "chiave", None, None)
    svc.calls = []
    done = threading.Event()

    def fake_sync(**kwargs):
        svc.calls.append(kwargs)
        done.set()
        return SyncResult(SyncOutcome.NO_CHANGES)

    svc.sync = fake_sync  # type: ignore[method-assign]
    svc.done = done
    return svc


def test_default_is_30_seconds(tmp_path):
    assert Settings(anki_data_dir=tmp_path).anki_sync_after_write_seconds == 30


def test_writes_are_grouped_into_one_sync(tmp_path):
    svc = service(tmp_path, 0.15)
    assert [svc.request_soon() for _ in range(10)] == [True] * 10
    assert svc.calls == []  # non blocca e non parte subito
    assert svc.done.wait(2)
    time.sleep(0.3)
    assert len(svc.calls) == 1
    assert svc.calls[0] == {"wait": True, "quick": True}
    # una scrittura dopo la sync ne arma un'altra
    svc.done.clear()
    assert svc.request_soon()
    assert svc.done.wait(2)
    assert len(svc.calls) == 2


def test_disabled_or_not_logged_in_does_nothing(tmp_path):
    off = service(tmp_path, 0)
    assert off.request_soon() is False
    anon = service(tmp_path, 0.05, logged_in=False)
    assert anon.request_soon() is False
    time.sleep(0.2)
    assert off.calls == [] and anon.calls == []


def test_conflict_waits_for_the_user(tmp_path):
    svc = service(tmp_path, 0.05)
    svc.last_result = SyncResult(SyncOutcome.FULL_SYNC_REQUIRED)
    assert svc.request_soon() is False


def test_cancel_pending(tmp_path):
    svc = service(tmp_path, 0.2)
    svc.request_soon()
    svc.cancel_pending()
    time.sleep(0.4)
    assert svc.calls == []


def test_waits_for_a_running_sync(tmp_path):
    """Una sola sync alla volta: quella dopo la scrittura aspetta quella in corso."""
    svc = SyncService(None, tmp_path / "auth.json", after_write_seconds=0.05)  # type: ignore[arg-type]
    svc._auth = StoredAuth("u", "chiave", None, None)
    order = []
    svc._sync_locked = lambda quick, timeout: order.append("sync") or SyncResult(SyncOutcome.NO_CHANGES)  # type: ignore[method-assign]
    with svc._run_lock:  # finge una sync in corso
        svc.request_soon()
        time.sleep(0.3)
        assert order == []
    deadline = time.time() + 2
    while not order and time.time() < deadline:
        time.sleep(0.02)
    assert order == ["sync"]


# ---- le rotte ---------------------------------------------------------------------------


class FakeSync:
    def __init__(self):
        self.requests = 0

    def request_soon(self):
        self.requests += 1
        return True

    def cancel_pending(self):
        pass


def test_routes_request_a_sync_after_a_real_write(client, make_token):
    fake = FakeSync()
    real = client.app.state.sync
    client.app.state.sync = fake
    try:
        headers, _ = make_token("claude")
        nid = post_batch(client, [basic("a")], headers=headers)["results"][0]["note_id"]
        assert fake.requests == 1
        # dry run, errori, letture e richieste vietate non scrivono: niente sync
        post_batch(client, [basic("b")], headers=headers, dry_run=True)
        post_batch(client, [basic("c", deck="Boh")], headers=headers)
        client.get("/api/hub/operations", headers=headers)
        assert client.post("/api/hub/operations/nonesiste/undo", headers=headers).status_code == 404
        assert client.delete(f"/api/notes/{nid}", headers=headers).status_code == 403
        assert fake.requests == 1

        r = client.patch(f"/api/notes/{nid}", json={"fields": {"Back": "x"}}, headers=headers)
        assert r.status_code == 200
        assert fake.requests == 2
        # annullare davvero scrive, quindi anche lì parte la sync; un secondo undo (409) no
        op = r.json()["operation_id"]
        assert client.post(f"/api/hub/operations/{op}/undo", headers=headers).status_code == 200
        assert fake.requests == 3
        assert client.post(f"/api/hub/operations/{op}/undo", headers=headers).status_code == 409
        assert fake.requests == 3
        # le scritture hub dalla sessione/amministratore contano
        assert client.post("/api/hub/decks", json={"name": "Nuovo"}).status_code == 200
        client.post("/api/hub/decks", json={"name": "Nuovo"})  # esisteva già
        assert fake.requests == 4
        assert client.post("/api/notes/tags", json={"note_ids": [nid], "add": ["t"]}).json() == {"updated": 1}
        other = client.post("/api/hub/decks", json={"name": "Altro"}).json()["id"]
        assert client.post(f"/api/notes/{nid}/move", json={"deck_id": other}).status_code == 200
        assert client.delete(f"/api/notes/{nid}").status_code == 204
        assert fake.requests == 8
    finally:
        client.app.state.sync = real


def test_without_ankiweb_the_write_returns_immediately(client):
    # con il servizio vero: non collegato → nessun timer, nessun lavoro
    assert client.app.state.sync.after_write_seconds == 30
    post_batch(client, [basic("a")])
    assert client.app.state.sync._soon_timer is None
