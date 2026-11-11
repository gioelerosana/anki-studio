"""Sync end-to-end contro il sync server locale del pacchetto `anki`.

Ogni test ha il suo server (dati in tmp_path), il backend dell'app e, quando
serve, un "desktop" che sincronizza lo stesso account.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.sync import ErrorKind, SyncOutcome, SyncResult, next_auto_delay

from .conftest import TOKEN
from .syncserver import Desktop, SyncServer

USER, PASSWORD = "studente@example.com", "segreta-123"
SEED = Path(__file__).resolve().parent.parent / "scripts" / "seed_dev.py"


def _seed(data_dir: Path) -> None:
    spec = importlib.util.spec_from_file_location("seed_dev", SEED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--data-dir", str(data_dir)]) == 0


@pytest.fixture
def server(tmp_path):
    s = SyncServer(tmp_path / "syncserver", {USER: PASSWORD})
    s.start()
    yield s
    s.stop()


def _settings(data_dir: Path, endpoint: str | None, **kw) -> Settings:
    base = dict(
        anki_api_token=TOKEN,
        anki_data_dir=data_dir,
        anki_auto_sync_minutes=0,
        anki_sync_on_startup=False,
        anki_sync_endpoint=endpoint,
        anki_sync_io_timeout=5,
    )
    base.update(kw)
    return Settings(**base)


class App:
    """TestClient + accesso diretto al servizio, riapribile come dopo un riavvio."""

    def __init__(self, data_dir: Path, endpoint: str | None, **kw) -> None:
        self.data_dir = data_dir
        self.settings = _settings(data_dir, endpoint, **kw)
        self._cm = TestClient(create_app(self.settings))
        self.c = self._cm.__enter__()
        self.c.headers["Authorization"] = f"Bearer {TOKEN}"

    @property
    def sync(self):
        return self.c.app.state.sync

    @property
    def manager(self):
        return self.c.app.state.manager

    def login(self) -> None:
        r = self.c.post("/api/sync/login", json={"username": USER, "password": PASSWORD})
        assert r.status_code == 204, r.text

    def wait_media(self, timeout: float = 15) -> dict:
        deadline = time.time() + timeout
        while True:
            st = self.c.get("/api/sync").json()
            if not st["media"]["active"]:
                return st
            if time.time() > deadline:
                raise TimeoutError("sync media dell'app non finita")
            time.sleep(0.05)

    def answer_first(self, deck_name: str, rating: int = 3) -> int:
        did = self.deck_id(deck_name)
        card = self.c.get(f"/api/decks/{did}/study").json()["card"]
        r = self.c.post(
            f"/api/decks/{did}/study/answer",
            json={"card_id": card["card_id"], "rating": rating, "time_taken_ms": 1500},
        )
        assert r.status_code == 200, r.text
        return card["card_id"]

    def deck_id(self, full_name: str) -> int:
        def walk(nodes):
            for n in nodes:
                if n["full_name"] == full_name:
                    return n["id"]
                found = walk(n["children"])
                if found:
                    return found
            return None

        did = walk(self.c.get("/api/decks").json())
        assert did, full_name
        return did

    def revlog_count(self) -> int:
        with self.manager.use() as col:
            return col.db.scalar("select count() from revlog")

    def close(self) -> None:
        self._cm.__exit__(None, None, None)


@pytest.fixture
def make_app(tmp_path):
    apps: list[App] = []

    def factory(name="app", endpoint=None, seed=False, **kw) -> App:
        d = tmp_path / name
        if seed and not (d / "collection.anki2").exists():
            _seed(d)
        a = App(d, endpoint, **kw)
        apps.append(a)
        return a

    yield factory
    for a in apps:
        try:
            a.close()
        except Exception:  # noqa: BLE001 - già chiusa nel test
            pass


@pytest.fixture
def desktop(tmp_path, server):
    d = Desktop(tmp_path / "desktop" / "collection.anki2", server.endpoint)
    d.login(USER, PASSWORD)
    yield d
    d.close()


# ---- login -------------------------------------------------------------------


def test_login_wrong_password_and_rate_limit(server, make_app):
    app = make_app(endpoint=server.endpoint, anki_login_max_failures=3)
    for _ in range(3):
        r = app.c.post("/api/sync/login", json={"username": USER, "password": "no"})
        assert r.status_code == 401
        assert "segreta" not in r.text
    r = app.c.post("/api/sync/login", json={"username": USER, "password": PASSWORD})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0
    st = app.c.get("/api/sync").json()
    assert st["logged_in"] is False
    assert st["endpoint"] == server.endpoint


def test_login_saves_only_the_key(server, make_app, caplog):
    app = make_app(endpoint=server.endpoint)
    with caplog.at_level("DEBUG"):
        app.login()
    stored = json.loads((app.data_dir / "sync_auth.json").read_text())
    assert stored["username"] == USER and stored["server"] == server.endpoint
    assert PASSWORD not in json.dumps(stored)
    assert (app.data_dir / "sync_auth.json").stat().st_mode & 0o777 == 0o600
    assert PASSWORD not in caplog.text and stored["hkey"] not in caplog.text
    st = app.c.get("/api/sync").json()
    assert st["logged_in"] and st["username"] == USER and st["running"] is None


# ---- prima sync --------------------------------------------------------------


def test_first_sync_full_upload_then_desktop_downloads(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True)
    app.login()
    r = app.c.post("/api/sync")
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "full_upload"
    st = app.wait_media()
    assert st["media"]["error"] is None

    assert desktop.sync() == "full_download"
    assert desktop.col.card_count() == 47
    assert {"sole.png", "città notte.png", "hablar.wav", "molecola.svg"} <= desktop.media_files()

    # due sync di fila dallo stesso client: la seconda non ha niente da fare
    assert app.c.post("/api/sync").json()["outcome"] in ("synced", "no_changes")
    assert app.c.post("/api/sync").json()["outcome"] == "no_changes"


def test_first_sync_full_download_with_media(server, make_app, desktop, tmp_path):
    # il desktop ha la collezione vera e la carica per primo
    _seed(tmp_path / "seed-src")
    desktop.close()
    import shutil

    shutil.rmtree(tmp_path / "desktop")
    shutil.copytree(tmp_path / "seed-src", tmp_path / "desktop")
    d = Desktop(tmp_path / "desktop" / "collection.anki2", server.endpoint)
    d.login(USER, PASSWORD)
    assert d.sync() == "full_upload"
    d.close()

    app = make_app(endpoint=server.endpoint)  # collezione vuota
    app.login()
    r = app.c.post("/api/sync")
    assert r.json()["outcome"] == "full_download", r.text
    app.wait_media()
    names = {n["full_name"] for n in app.c.get("/api/decks").json()}
    assert "Lingue" in names
    assert app.c.get("/api/media/sole.png").status_code == 200
    assert app.c.get("/api/media/citt%C3%A0%20notte.png").status_code == 200
    # collezione vuota: niente backup inutile prima del download
    assert not list((app.data_dir / "backups").glob("*.colpkg"))


# ---- sync normale ------------------------------------------------------------


def _initial(app: App, desktop: Desktop) -> None:
    """Prima sync: l'app carica la collezione di prova, il desktop la scarica."""
    app.login()
    assert app.c.post("/api/sync").json()["outcome"] == "full_upload"
    app.wait_media()
    assert desktop.sync() == "full_download"


def test_normal_sync_reviews_on_both_sides(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True)
    _initial(app, desktop)
    base_revlog = app.revlog_count()

    # review sull'iPad (app) e sul desktop, su mazzi diversi
    app.answer_first("Lingue::Spagnolo::Verbi")
    app.answer_first("Lingue::Spagnolo::Verbi")
    did = desktop.col.decks.id_for_name("Scienze::Matematica")
    desktop.col.decks.select(did)
    card = desktop.col.sched.getCard()
    card.start_timer()
    desktop.col.sched.answerCard(card, 3)
    # e una nota nuova dal desktop
    note = desktop.col.new_note(desktop.col.models.by_name("Basic"))
    note["Front"], note["Back"] = "Capitale della Finlandia", "Helsinki"
    desktop.col.add_note(note, desktop.col.decks.id("Default"))

    assert app.c.post("/api/sync").json()["outcome"] == "synced"
    assert desktop.sync() == "synced"
    assert app.c.post("/api/sync").json()["outcome"] == "synced"  # riceve la review del desktop

    assert app.revlog_count() == base_revlog + 3
    assert desktop.col.db.scalar("select count() from revlog") == base_revlog + 3
    with app.manager.use() as col:
        assert col.find_notes('"Front:Capitale della Finlandia"')
    st = app.c.get("/api/sync").json()
    assert st["last_result"]["outcome"] == "synced" and not st["full_sync_required"]


def test_shutdown_syncs_pending_reviews(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True)
    _initial(app, desktop)
    app.answer_first("Lingue::Spagnolo::Verbi")
    app.close()  # lo spegnimento fa un'ultima sync
    assert desktop.sync() == "synced"
    assert desktop.col.db.scalar("select count() from revlog") == app_revlog_after(app)


def app_revlog_after(app: App) -> int:
    from anki.collection import Collection

    col = Collection(str(app.settings.collection_path))
    try:
        return col.db.scalar("select count() from revlog")
    finally:
        col.close()


# ---- conflitto ---------------------------------------------------------------


def _make_conflict(app: App, desktop: Desktop) -> None:
    """Il desktop cambia lo schema (un campo in più) e carica: l'app non può più fondere."""
    _initial(app, desktop)
    app.answer_first("Lingue::Spagnolo::Verbi")  # modifica locale che andrebbe persa
    mm = desktop.col.models
    basic = mm.by_name("Basic")
    mm.add_field(basic, mm.new_field("Nota del desktop"))
    mm.update_dict(basic)
    assert desktop.sync() == "conflict"
    assert desktop.sync(on_conflict="upload") == "full_upload"


def test_conflict_requires_explicit_choice_download(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True)
    _make_conflict(app, desktop)

    r = app.c.post("/api/sync")
    assert r.status_code == 409
    st = app.c.get("/api/sync").json()
    assert st["full_sync_required"] is True
    assert st["last_result"]["outcome"] == "full_sync_required"
    # la collezione del server non è stata toccata
    with app.manager.use() as col:
        assert "Nota del desktop" not in col.models.field_names(col.models.by_name("Basic"))

    r = app.c.post("/api/sync/full", json={"direction": "download"})
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "full_download"
    with app.manager.use() as col:
        assert "Nota del desktop" in col.models.field_names(col.models.by_name("Basic"))
    # prima di sostituire la collezione ne è stata fatta una copia
    backups = list((app.data_dir / "backups").glob("*.colpkg"))
    assert backups, "manca il backup prima del download completo"
    st = app.wait_media()
    assert st["full_sync_required"] is False
    assert app.c.post("/api/sync").json()["outcome"] == "no_changes"


def test_conflict_resolved_with_upload(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True)
    _make_conflict(app, desktop)
    assert app.c.post("/api/sync").status_code == 409
    revlog = app.revlog_count()

    r = app.c.post("/api/sync/full", json={"direction": "upload"})
    assert r.json()["outcome"] == "full_upload", r.text
    # ora è il desktop a dover scegliere: scarica e riceve la review dell'app
    assert desktop.sync() == "conflict"
    assert desktop.sync(on_conflict="download") == "full_download"
    assert desktop.col.db.scalar("select count() from revlog") == revlog


def test_refuses_to_upload_empty_collection(server, make_app, desktop, tmp_path):
    _seed(tmp_path / "desktop-seed")
    src = Desktop(tmp_path / "desktop-seed" / "collection.anki2", server.endpoint)
    src.login(USER, PASSWORD)
    assert src.sync() == "full_upload"
    src.close()

    app = make_app(endpoint=server.endpoint)  # vuota
    app.login()
    r = app.c.post("/api/sync/full", json={"direction": "upload"})
    assert r.status_code == 409
    assert "vuota" in r.json()["detail"]
    # AnkiWeb (il server) ha ancora tutto
    assert desktop.sync() == "full_download"
    assert desktop.col.card_count() == 47


# ---- media -------------------------------------------------------------------


def test_media_upload_and_download(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True)
    _initial(app, desktop)

    # dall'app: un file nuovo usato da una nota
    with app.manager.use() as col:
        name = col.media.write_data("dall-ipad.png", b"\x89PNG ipad")
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"], note["Back"] = f'<img src="{name}">', "foto"
        col.add_note(note, col.decks.id("Default"))
    assert app.c.post("/api/sync").json()["outcome"] == "synced"
    app.wait_media()
    assert desktop.sync() == "synced"
    assert "dall-ipad.png" in desktop.media_files()

    # dal desktop: un file nuovo arriva all'app
    name = desktop.col.media.write_data("dal-desktop.wav", b"RIFF desktop")
    note = desktop.col.new_note(desktop.col.models.by_name("Basic"))
    note["Front"], note["Back"] = "suono", f"[sound:{name}]"
    desktop.col.add_note(note, desktop.col.decks.id("Default"))
    assert desktop.sync() == "synced"
    assert app.c.post("/api/sync").json()["outcome"] == "synced"
    app.wait_media()
    assert app.c.get("/api/media/dal-desktop.wav").content == b"RIFF desktop"


def test_quick_sync_without_changes_still_syncs_media(server, make_app, desktop):
    """Sync automatica (quick): collezione allineata ma un file nuovo sul server.
    Il controllo leggero dice "niente da fare", i media vanno scaricati comunque."""
    app = make_app(endpoint=server.endpoint, seed=True)
    _initial(app, desktop)
    app.c.post("/api/sync")
    assert app.c.post("/api/sync").json()["outcome"] == "no_changes"  # l'app ha sincronizzato per ultima
    # il desktop carica solo un file (sync dei soli media, la collezione sul server non cambia)
    desktop.col.media.write_data("solo-media.png", b"\x89PNG solo")
    desktop.col.sync_media(desktop.auth)
    desktop.wait_media()

    with app.manager.use() as col:
        before = col.db.first("select mod, ls, usn from col")
    result = app.sync.sync(quick=True)
    assert result.outcome == SyncOutcome.NO_CHANGES
    app.wait_media()
    assert app.c.get("/api/media/solo-media.png").content == b"\x89PNG solo"
    with app.manager.use() as col:
        assert col.db.first("select mod, ls, usn from col") == before


def test_quick_sync_detects_local_changes(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True)
    _initial(app, desktop)
    app.c.post("/api/sync")
    app.answer_first("Lingue::Spagnolo::Verbi")
    assert app.sync.sync(quick=True).outcome == SyncOutcome.SYNCED


# ---- endpoint ----------------------------------------------------------------


def test_endpoint_change_requires_new_login(server, make_app, tmp_path):
    app = make_app(endpoint=server.endpoint, seed=True)
    app.login()
    app.close()

    # stessa cartella dati, endpoint diverso (es. si passa da AnkiWeb a un server proprio)
    moved = App(app.data_dir, "http://127.0.0.1:9/")
    try:
        st = moved.c.get("/api/sync").json()
        assert st["logged_in"] is False and st["endpoint_mismatch"] is True
        assert moved.c.post("/api/sync").status_code == 401
        # la chiave vecchia non viene cancellata: tornando all'endpoint di prima funziona ancora
        assert (app.data_dir / "sync_auth.json").exists()
    finally:
        moved.close()
    back = App(app.data_dir, server.endpoint.rstrip("/"))  # lo slash finale non conta
    try:
        assert back.c.get("/api/sync").json()["logged_in"] is True
        # il primo upload l'ha già fatto la sync allo spegnimento di `app`
        assert back.c.post("/api/sync").json()["outcome"] == "no_changes"
    finally:
        back.close()


def test_server_redirects_to_new_endpoint(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True)
    _initial(app, desktop)
    # AnkiWeb può spostare l'account su un altro host: simuliamo la risposta
    col = app.manager.col
    real = col.sync_collection
    new = f"http://localhost:{server.port}/"

    def redirecting(auth, sync_media):
        out = real(auth, sync_media)
        out.new_endpoint = new
        return out

    col.sync_collection = redirecting
    try:
        app.answer_first("Lingue::Spagnolo::Verbi")
        assert app.c.post("/api/sync").json()["outcome"] == "synced"
    finally:
        del col.sync_collection
    stored = json.loads((app.data_dir / "sync_auth.json").read_text())
    assert stored["endpoint"] == new and stored["server"] == server.endpoint
    # le sync successive usano il nuovo endpoint
    assert app.sync._sync_auth().endpoint == new
    assert app.c.post("/api/sync").json()["outcome"] == "no_changes"


# ---- errori ------------------------------------------------------------------


def test_revoked_key_logs_out_without_touching_data(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True)
    _initial(app, desktop)
    app.answer_first("Lingue::Spagnolo::Verbi")
    revlog = app.revlog_count()

    server.restart({USER: "password-cambiata"})  # la vecchia chiave non vale più
    r = app.c.post("/api/sync")
    assert r.status_code == 401
    assert "rifai il login" in r.json()["detail"]
    st = app.c.get("/api/sync").json()
    assert st["logged_in"] is False
    assert st["last_result"]["error_kind"] == "auth"
    assert not (app.data_dir / "sync_auth.json").exists()
    assert app.revlog_count() == revlog  # niente perso

    r = app.c.post("/api/sync/login", json={"username": USER, "password": "password-cambiata"})
    assert r.status_code == 204
    assert app.c.post("/api/sync").json()["outcome"] == "synced"


def test_network_error_is_reported_and_study_continues(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True)
    _initial(app, desktop)
    server.stop()
    r = app.c.post("/api/sync")
    assert r.status_code == 502
    st = app.c.get("/api/sync").json()
    assert st["last_result"]["error_kind"] == "network"
    assert st["logged_in"] is True  # un errore di rete non scollega
    app.answer_first("Lingue::Spagnolo::Verbi")

    server.start()
    assert app.c.post("/api/sync").json()["outcome"] == "synced"


# ---- concorrenza -------------------------------------------------------------


def test_one_sync_at_a_time_and_status_while_running(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True, anki_busy_timeout=0.2)
    _initial(app, desktop)
    app.answer_first("Lingue::Spagnolo::Verbi")

    col = app.manager.col
    real = col.sync_collection
    entered = threading.Event()
    release = threading.Event()

    def slow(auth, sync_media):
        entered.set()
        release.wait(10)
        return real(auth, sync_media)

    col.sync_collection = slow
    results: list = []
    t = threading.Thread(target=lambda: results.append(app.c.post("/api/sync")))
    t.start()
    try:
        assert entered.wait(5)
        st = app.c.get("/api/sync").json()  # risponde subito
        assert st["running"] == "normal" and st["running_since"]
        assert app.sync.sync(wait=False) is None  # la sync automatica salta il giro
        r = app.c.get("/api/decks")
        assert r.status_code == 503 and r.headers["retry-after"]
        assert "Sync in corso" in r.json()["detail"]
        h = app.c.get("/api/health")
        assert h.status_code == 200 and h.json()["collection"] == "busy"
    finally:
        release.set()
        t.join(10)
        del col.sync_collection
    assert results[0].status_code == 200 and results[0].json()["outcome"] == "synced"
    assert app.c.get("/api/sync").json()["running"] is None
    assert app.c.get("/api/health").json()["collection"] == "open"


def test_auto_sync_backoff():
    err = SyncResult(SyncOutcome.ERROR, error_kind=ErrorKind.NETWORK)
    delays, failures = [], 0
    for _ in range(8):
        d, failures = next_auto_delay(err, failures, 600)
        delays.append(d)
    assert delays[:5] == [30, 60, 120, 240, 480] and delays[5:] == [600, 600, 600]
    assert next_auto_delay(SyncResult(SyncOutcome.SYNCED), failures, 600) == (600, 0)
    # un conflitto o un logout non si risolvono riprovando
    conflict = SyncResult(SyncOutcome.FULL_SYNC_REQUIRED)
    assert next_auto_delay(conflict, 3, 600) == (600, 0)
    refused = SyncResult(SyncOutcome.ERROR, error_kind=ErrorKind.REFUSED)
    assert next_auto_delay(refused, 0, 600) == (600, 0)


def test_startup_sync_runs_in_background(server, make_app, desktop):
    app = make_app(endpoint=server.endpoint, seed=True)
    _initial(app, desktop)
    desktop_note = desktop.col.new_note(desktop.col.models.by_name("Basic"))
    desktop_note["Front"], desktop_note["Back"] = "avvio", "sync"
    desktop.col.add_note(desktop_note, desktop.col.decks.id("Default"))
    assert desktop.sync() == "synced"
    app.close()

    restarted = App(app.data_dir, server.endpoint, anki_sync_on_startup=True)
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            st = restarted.c.get("/api/sync").json()
            if st["last_result"]:
                break
            time.sleep(0.05)
        assert st["last_result"]["outcome"] == "synced"
        with restarted.manager.use() as col:
            assert col.find_notes('"Front:avvio"')
    finally:
        restarted.close()


def test_agent_notes_reach_the_desktop_without_a_manual_sync(server, make_app, desktop):
    """Una batch da un token parte da sola verso il server di sync (debounce di 1 s)
    e il desktop la riceve; più scritture ravvicinate fanno una sola sync."""
    app = make_app(endpoint=server.endpoint, seed=True, anki_sync_after_write_seconds=1)
    _initial(app, desktop)
    token = app.c.post("/api/tokens", json={"name": "claude"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    for i in range(3):
        r = app.c.post(
            "/api/hub/notes/batch",
            headers=headers,
            json={
                "notes": [
                    {
                        "deck": "Lingue::Spagnolo::Verbi",
                        "notetype": "Basic",
                        "fields": {"Front": f"agente {i}", "Back": "x"},
                        "external_id": f"agente-{i}",
                    }
                ]
            },
        )
        assert r.status_code == 200 and r.json()["created"] == 1

    deadline = time.time() + 15
    while time.time() < deadline:
        last = app.sync.last_result
        if (
            last is not None
            and last.outcome == SyncOutcome.SYNCED
            and app.sync.running is None
            and app.sync._soon_timer is None
        ):
            break
        time.sleep(0.1)
    assert app.sync.last_result is not None and app.sync.last_result.outcome == SyncOutcome.SYNCED

    assert desktop.sync() == "synced"
    ids = desktop.col.find_notes("tag:agent::claude")
    assert len(ids) == 3
    note = desktop.col.get_note(ids[0])
    # arrivano come note normali, con la provenienza, e le carte sono attive anche sull'altro dispositivo
    assert any("ext::agente-" in t for t in note.tags)
    assert all(desktop.col.get_card(c).queue == 0 for c in note.card_ids())
