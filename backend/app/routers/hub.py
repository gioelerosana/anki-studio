"""Hub delle flashcard: creazione da agenti, mazzi, bozze, anteprime (docs/PIANO-HUB.md).

Le rotte sono sottili: la logica sta in `app/hub.py` (la riusa anche il server MCP).
Chi può chiamarle lo decide `require_auth` (matrice dei permessi in `app/security.py`),
non queste funzioni: qui si legge solo l'identità per la provenienza e il flag `review`.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import hub
from ..collection import CollectionManager
from ..deps import get_identity, get_manager, get_sync
from ..schemas import (
    CardPreview,
    DraftApproveOut,
    DraftDiscardOut,
    DraftList,
    HubBatchIn,
    HubBatchOut,
    HubDeckIn,
    HubDeckOut,
    HubSummary,
    NoteIdsIn,
)
from ..security import Identity
from ..sync import SyncService

router = APIRouter(tags=["hub"])

_MAX_LIMIT = 200


def hub_http_error(e: hub.HubError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if e.kind == "not_found" else 422
    return HTTPException(code, str(e))


@router.post("/hub/notes/batch", response_model=HubBatchOut)
def create_notes_batch(
    body: HubBatchIn,
    identity: Identity = Depends(get_identity),
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    """Fino a 100 note, ognuna col suo esito. `dry_run` non scrive niente. Una batch è
    una sola operazione annullabile. Le note di un token portano `agent::<nome>`; con
    `review` (token) o `draft` sono bozze: carte sospese e tag `hub::bozza`."""
    with manager.use() as col:
        out = hub.create_batch(col, body, agent=identity.agent, review=identity.review)
    if not out.dry_run and (out.created or out.updated):
        sync.request_soon()
    return out


@router.post("/hub/decks", response_model=HubDeckOut)
def create_deck(
    body: HubDeckIn,
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    """Idempotente: se il mazzo esiste lo restituisce con `created: false`."""
    with manager.use() as col:
        try:
            out = hub.create_deck(col, body.name)
        except hub.HubError as e:
            raise hub_http_error(e)
    if out.created:
        sync.request_soon()
    return out


@router.get("/hub/summary", response_model=HubSummary)
def summary(manager: CollectionManager = Depends(get_manager)):
    with manager.use() as col:
        return hub.summary(col)


@router.get("/hub/drafts", response_model=DraftList)
def list_drafts(
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    manager: CollectionManager = Depends(get_manager),
):
    with manager.use() as col:
        return hub.list_drafts(col, limit, offset)


@router.post("/hub/drafts/approve", response_model=DraftApproveOut)
def approve_drafts(
    body: NoteIdsIn,
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    """Le carte tornano attive e il tag `hub::bozza` sparisce. Gli id che non sono bozze si ignorano."""
    with manager.use() as col:
        approved = hub.approve_drafts(col, body.note_ids)
    if approved:
        sync.request_soon()
    return DraftApproveOut(approved=approved)


@router.post("/hub/drafts/discard", response_model=DraftDiscardOut)
def discard_drafts(
    body: NoteIdsIn,
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    """Cancella le note scelte, ma solo se sono bozze: le altre restano dove sono."""
    with manager.use() as col:
        discarded = hub.discard_drafts(col, body.note_ids)
    if discarded:
        sync.request_soon()
    return DraftDiscardOut(discarded=discarded)


@router.get("/cards/{card_id}/preview", response_model=CardPreview)
def card_preview(card_id: int, manager: CollectionManager = Depends(get_manager)):
    """Come una carta di studio, ma senza coda: vale anche per le carte sospese (bozze)."""
    with manager.use() as col:
        try:
            return hub.card_preview(col, card_id)
        except hub.HubError as e:
            raise hub_http_error(e)
