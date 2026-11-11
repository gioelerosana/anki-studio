"""Hub delle flashcard: creazione da agenti, mazzi, diario con annullamento, anteprime
(docs/PIANO-HUB.md).

Le rotte sono sottili: la logica sta in `app/hub.py` e `app/journal.py` (le riusa anche il server
MCP). Chi può chiamarle lo decide `require_auth` (matrice dei permessi in `app/security.py`),
non queste funzioni: qui si legge solo l'identità per la provenienza e per il diario.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import hub, journal
from ..collection import CollectionManager
from ..deps import get_identity, get_journal, get_manager, get_sync
from ..schemas import (
    CardPreview,
    HubBatchIn,
    HubBatchOut,
    HubDeckIn,
    HubDeckOut,
    OperationList,
    UndoOut,
)
from ..security import Identity
from ..sync import SyncService

router = APIRouter(tags=["hub"])

_MAX_LIMIT = 200


def hub_http_error(e: hub.HubError) -> HTTPException:
    code = {
        "not_found": status.HTTP_404_NOT_FOUND,
        "too_large": status.HTTP_413_CONTENT_TOO_LARGE,
    }.get(e.kind, 422)
    return HTTPException(code, str(e))


@router.post("/hub/notes/batch", response_model=HubBatchOut)
def create_notes_batch(
    body: HubBatchIn,
    identity: Identity = Depends(get_identity),
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
    ops: journal.Journal = Depends(get_journal),
):
    """Fino a 100 note, ognuna col suo esito. `dry_run` non scrive niente. Le note entrano subito,
    normali e attive; quelle di un token portano `agent::<nome>`. Se la batch scrive qualcosa
    finisce nel diario come una sola operazione: `operation_id` per annullarla (`/hub/operations`).
    Tetti: 200 KB per campo e 2 MB per batch (422)."""
    with manager.use() as col:
        try:
            out = hub.create_batch(col, body, agent=identity.agent, journal=ops, actor=identity.actor)
        except hub.HubError as e:  # batch troppo grande: 422 prima di scrivere
            raise hub_http_error(e)
    if not out.dry_run and (out.created or out.updated):
        sync.request_soon()
    return out


@router.post("/hub/decks", response_model=HubDeckOut)
def create_deck(
    body: HubDeckIn,
    identity: Identity = Depends(get_identity),
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
    ops: journal.Journal = Depends(get_journal),
):
    """Idempotente: se il mazzo esiste lo restituisce con `created: false`."""
    with manager.use() as col:
        try:
            out = hub.create_deck(col, body.name, journal=ops, actor=identity.actor)
        except hub.HubError as e:
            raise hub_http_error(e)
    if out.created:
        sync.request_soon()
    return out


def _own(identity: Identity) -> str | None:
    """Chi ha uno scope (token, OAuth) vede e annulla solo le operazioni del proprio agente."""
    return identity.agent if identity.scoped else None


@router.get("/hub/operations", response_model=OperationList)
def list_operations(
    limit: int = Query(50, ge=1, le=_MAX_LIMIT, description=f"Da 1 a {_MAX_LIMIT}"),
    identity: Identity = Depends(get_identity),
    ops: journal.Journal = Depends(get_journal),
):
    """Il diario delle operazioni degli agenti, dalla più recente: le ultime 200 e al massimo 30
    giorni. Sessione e `ANKI_API_TOKEN` le vedono tutte; un token vede solo le proprie. Non
    tocca la collezione."""
    return OperationList(operations=ops.list(agent=_own(identity), limit=limit))


@router.post("/hub/operations/{operation_id}/undo", response_model=UndoOut)
def undo_operation(
    operation_id: str,
    identity: Identity = Depends(get_identity),
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
    ops: journal.Journal = Depends(get_journal),
):
    """Annulla un'operazione: cancella le note create (se nessuno le ha toccate o studiate), riporta
    com'erano le note aggiornate (se nessuno le ha modificate dopo) ed elimina i mazzi creati (se
    vuoti). Ciò che non si può annullare si salta e torna in `skipped` con il motivo; l'operazione
    resta `partial` e si può ritentare. Non annulla media né sync. 404 se l'id non esiste (o è
    di un altro agente), 409 se è già annullata, 403 a un token `read`."""
    with manager.use() as col:
        try:
            out = ops.undo(col, operation_id, agent=_own(identity))
        except journal.OperationNotFound as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
        except journal.AlreadyUndone as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    if out.restored or out.deleted:
        sync.request_soon()
    return out


@router.get("/cards/{card_id}/preview", response_model=CardPreview)
def card_preview(card_id: int, manager: CollectionManager = Depends(get_manager)):
    """Come una carta di studio, ma senza coda: vale anche per le carte sospese."""
    with manager.use() as col:
        try:
            return hub.card_preview(col, card_id)
        except hub.HubError as e:
            raise hub_http_error(e)
