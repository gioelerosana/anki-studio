import anki.lang
import pytest
from anki.collection import Collection
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TOKEN = "test-token-abcdefghijklmnop"


@pytest.fixture(autouse=True)
def _english_stock_notetypes():
    """L'app imposta la lingua di Anki (ANKI_LANG=it) per tutto il processo: le
    collezioni create dopo avrebbero "Base" al posto di "Basic". I test (e lo
    script di seed) creano le collezioni in inglese, come una collezione vera."""
    anki.lang.set_lang("en")
    yield
    anki.lang.set_lang("en")


@pytest.fixture
def seeded(tmp_path):
    """Collezione locale con un mazzo, 3 note base e un file media."""
    settings = Settings(
        anki_api_token=TOKEN,
        anki_data_dir=tmp_path,
        anki_auto_sync_minutes=0,
        anki_sync_on_startup=False,
        ankiweb_username=None,
        ankiweb_password=None,
    )
    col = Collection(str(settings.collection_path))
    did = col.decks.id("Spagnolo::Verbi")
    basic = col.models.by_name("Basic")
    for front, back in [("ser", "essere"), ("tener", "avere"), ("ir", "andare")]:
        n = col.new_note(basic)
        n["Front"] = f'{front} <img src="pic.png">'
        n["Back"] = f"{back} [sound:{front}.mp3]"
        col.add_note(n, did)
    media_dir = col.media.dir()
    open(f"{media_dir}/pic.png", "wb").write(b"\x89PNG fake")
    col.close()
    return settings, did


@pytest.fixture
def client(seeded):
    settings, did = seeded
    with TestClient(create_app(settings)) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        c.deck_id = did
        yield c


@pytest.fixture
def make_token(client):
    """Crea un token per gli agenti (con l'accesso amministratore del client) e restituisce
    gli header da passare alle richieste e la risposta di creazione."""

    def make(name="claude", scope="write", review=False):
        r = client.post("/api/tokens", json={"name": name, "scope": scope, "review": review})
        assert r.status_code == 201, r.text
        body = r.json()
        return {"Authorization": f"Bearer {body['token']}"}, body

    return make


def note_count(client) -> int:
    with client.app.state.manager.use() as col:
        return col.note_count()
