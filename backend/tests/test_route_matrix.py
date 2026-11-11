"""Deny-by-default davvero: ogni rotta `/api/*` dell'app deve essere classificata qui. Una rotta
nuova che non compare nella tabella fa fallire il test finché qualcuno non decide chi la può
chiamare (e, se è per i token, la aggiunge anche a `security._READ_ROUTES`/`_WRITE_ROUTES`)."""

import re

import pytest
from fastapi.routing import APIRoute

from app.security import Identity, require_auth, token_may

READ, WRITE, ADMIN, PUBLIC = "read", "write", "admin", "public"

# (metodo, percorso come dichiarato) → chi può chiamarla
#   read    token read e write (solo letture)
#   write   solo token write (e sessione/amministratore)
#   admin   solo sessione e ANKI_API_TOKEN: un token con scope riceve 403
#   public  si autentica da sé (login, WebSocket del telecomando) o non serve
MATRIX = {
    ("GET", "/api/health"): PUBLIC,
    ("GET", "/api/auth/login"): PUBLIC,
    ("GET", "/api/auth/callback"): PUBLIC,
    ("POST", "/api/auth/logout"): PUBLIC,
    ("WEBSOCKET", "/api/remote"): PUBLIC,
    ("GET", "/api/decks"): READ,
    ("GET", "/api/notetypes"): READ,
    ("GET", "/api/search/notes"): READ,
    ("GET", "/api/tags"): READ,
    ("GET", "/api/notes/{note_id}"): READ,
    ("GET", "/api/cards/{card_id}/preview"): READ,
    ("GET", "/api/hub/operations"): READ,
    ("GET", "/api/sync"): READ,
    ("POST", "/api/hub/notes/batch"): WRITE,
    ("POST", "/api/hub/decks"): WRITE,
    ("POST", "/api/sync"): WRITE,
    ("POST", "/api/media"): WRITE,
    ("POST", "/api/hub/operations/{operation_id}/undo"): WRITE,
    ("PATCH", "/api/notes/{note_id}"): WRITE,
    # tutto il resto è riservato all'utente
    ("GET", "/api/stats"): ADMIN,
    ("GET", "/api/stats/today"): ADMIN,
    ("GET", "/api/auth/me"): ADMIN,
    ("GET", "/api/media/{filename}"): ADMIN,
    ("GET", "/api/decks/{deck_id}/study"): ADMIN,
    ("GET", "/api/decks/{deck_id}/options"): ADMIN,
    ("POST", "/api/decks/{deck_id}/study/answer"): ADMIN,
    ("POST", "/api/decks/{deck_id}/study/undo"): ADMIN,
    ("POST", "/api/decks/{deck_id}/extend-limits"): ADMIN,
    ("POST", "/api/cards/{card_id}/bury"): ADMIN,
    ("POST", "/api/cards/{card_id}/suspend"): ADMIN,
    ("POST", "/api/cards/{card_id}/type-answer"): ADMIN,
    ("POST", "/api/cards/{card_id}/flag"): ADMIN,
    ("POST", "/api/notes"): ADMIN,
    ("POST", "/api/notes/{note_id}/move"): ADMIN,
    ("DELETE", "/api/notes/{note_id}"): ADMIN,
    ("POST", "/api/notes/tags"): ADMIN,
    ("POST", "/api/sync/login"): ADMIN,
    ("POST", "/api/sync/logout"): ADMIN,
    ("POST", "/api/sync/full"): ADMIN,
    ("GET", "/api/tokens"): ADMIN,
    ("POST", "/api/tokens"): ADMIN,
    ("PATCH", "/api/tokens/{token_id}"): ADMIN,
    ("DELETE", "/api/tokens/{token_id}"): ADMIN,
}


def walk_routes(app):
    """(metodo, percorso, protetta da require_auth) per ogni rotta `/api/*`, entrando anche nei
    router inclusi. FastAPI cambia la forma interna dei router inclusi tra le versioni:
    `_check_walk_is_complete` fa fallire il test se non si vede più tutto."""
    for route in app.routes:
        include = getattr(route, "include_context", None)
        if include is not None:
            via = [d.dependency for d in include.dependencies]
            for sub in include.included_router.routes:
                yield from _expand(include.prefix + sub.path, sub, require_auth in via)
        else:
            yield from _expand(route.path, route, require_auth in [d.call for d in getattr(getattr(route, "dependant", None), "dependencies", [])])


def _expand(path, route, protected):
    if not path.startswith("/api/"):
        return
    if isinstance(route, APIRoute):
        own = require_auth in [d.call for d in route.dependant.dependencies]
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield method, path, protected or own
    else:  # WebSocket
        yield "WEBSOCKET", path, False


@pytest.fixture
def routes(client):
    found = list(walk_routes(client.app))
    # tutto ciò che compare nello schema OpenAPI deve esserci anche nel giro sulle rotte
    # (nello schema mancano solo login e callback, nascosti di proposito)
    openapi = {
        (m.upper(), p)
        for p, ops in client.app.openapi()["paths"].items()
        if p.startswith("/api/")
        for m in ops
    }
    assert openapi <= {(m, p) for m, p, _ in found}, "il giro sulle rotte non si legge più"
    return found


def concrete(path):
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_api_route_is_classified(routes):
    seen = {(m, p) for m, p, _ in routes}
    unclassified = seen - set(MATRIX)
    assert not unclassified, (
        f"Rotte nuove da classificare in MATRIX (e in security._READ_ROUTES/_WRITE_ROUTES se servono ai token): {sorted(unclassified)}"
    )
    stale = set(MATRIX) - seen
    assert not stale, f"Voci della matrice senza rotta: {sorted(stale)}"
    assert len(seen) >= 42  # se il giro sulle rotte si rompe non deve passare "a vuoto"


def test_only_the_public_routes_skip_require_auth(routes):
    for method, path, protected in routes:
        assert protected == (MATRIX[(method, path)] != PUBLIC), (method, path)


def test_the_token_matrix_agrees_with_the_classification(routes):
    read = Identity(kind="token", name="r", scope="read")
    write = Identity(kind="token", name="w", scope="write")
    for method, path, _ in routes:
        kind = MATRIX[(method, path)]
        if kind == PUBLIC:
            continue
        p = concrete(path)
        assert token_may(read, method, p) == (kind == READ), (method, path, "read")
        assert token_may(write, method, p) == (kind in (READ, WRITE)), (method, path, "write")
        # sessione e amministratore: sempre
        assert token_may(Identity(kind="session", name="x"), method, p)


def test_http_answers_match_the_classification(client, make_token, routes):
    """Non solo la tabella: la richiesta vera riceve 403 quando deve."""
    read_h, _ = make_token("lettore", scope="read")
    write_h, _ = make_token("scrittore", scope="write")
    for method, path, _ in routes:
        kind = MATRIX[(method, path)]
        if kind == PUBLIC:
            continue
        url = concrete(path)
        r = client.request(method, url, json={}, headers=read_h)
        assert (r.status_code == 403) == (kind != READ), (method, path, "read", r.status_code)
        w = client.request(method, url, json={}, headers=write_h)
        assert (w.status_code == 403) == (kind == ADMIN), (method, path, "write", w.status_code)


def test_a_new_unlisted_route_is_caught(client):
    """Il controllo di sopra non passa "a vuoto": una rotta aggiunta senza classificarla si vede."""
    client.app.add_api_route("/api/inventata", lambda: {}, methods=["GET"])
    seen = {(m, p) for m, p, _ in walk_routes(client.app)}
    assert ("GET", "/api/inventata") in seen and ("GET", "/api/inventata") not in MATRIX
