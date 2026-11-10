from fastapi import APIRouter, Depends, HTTPException, Response, status

from anki.collection import Collection
from anki.consts import MODEL_CLOZE
from anki.notes import Note, NoteFieldsCheckResult

from .. import hub
from ..collection import CollectionManager
from ..deps import get_identity, get_manager, get_sync
from ..schemas import (
    NoteIn,
    NoteMoveIn,
    NoteOut,
    Notetype,
    NotetypeField,
    NoteTagsIn,
    NoteTagsOut,
    NoteUpdate,
)
from ..security import Identity
from ..sync import SyncService
from .hub import hub_http_error

router = APIRouter(tags=["notes"])

_CHECK_ERRORS = {
    NoteFieldsCheckResult.EMPTY: "Il primo campo è vuoto",
    NoteFieldsCheckResult.DUPLICATE: "Esiste già una nota con questo primo campo",
    NoteFieldsCheckResult.MISSING_CLOZE: "Manca una cloze ({{c1::...}})",
    NoteFieldsCheckResult.NOTETYPE_NOT_CLOZE: "Questo tipo di nota non supporta le cloze",
    NoteFieldsCheckResult.FIELD_NOT_CLOZE: "Cloze in un campo che non la supporta",
}


@router.get("/notetypes", response_model=list[Notetype])
def list_notetypes(manager: CollectionManager = Depends(get_manager)):
    with manager.use() as col:
        out = []
        for nt in col.models.all_names_and_ids():
            model = col.models.get(nt.id)
            out.append(
                Notetype(
                    id=nt.id,
                    name=nt.name,
                    is_cloze=model["type"] == MODEL_CLOZE,
                    fields=[NotetypeField(name=f["name"], ord=f["ord"]) for f in model["flds"]],
                )
            )
        return out


def _apply_fields(note: Note, fields: dict[str, str]) -> None:
    unknown = set(fields) - set(note.keys())
    if unknown:
        raise HTTPException(
            422,
            f"Campi inesistenti per questo tipo di nota: {sorted(unknown)}",
        )
    for k, v in fields.items():
        note[k] = v


def _check(note: Note, allow_duplicate: bool = False) -> None:
    result = note.fields_check()
    if result == NoteFieldsCheckResult.NORMAL:
        return
    if allow_duplicate and result == NoteFieldsCheckResult.DUPLICATE:
        return
    raise HTTPException(
        422, _CHECK_ERRORS.get(result, "Nota non valida")
    )


def _note_out(note: Note) -> NoteOut:
    return NoteOut(
        id=note.id,
        notetype_id=note.mid,
        fields=dict(note.items()),
        tags=list(note.tags),
        card_ids=list(note.card_ids()),
    )


def _get_note(col: Collection, note_id: int) -> Note:
    try:
        return col.get_note(note_id)
    except Exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nota non trovata")


@router.post("/notes", response_model=NoteOut, status_code=201)
def create_note(
    body: NoteIn,
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    with manager.use() as col:
        model = col.models.get(body.notetype_id)
        if model is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Tipo di nota non trovato")
        if col.decks.get(body.deck_id, default=False) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Mazzo non trovato")
        note = col.new_note(model)
        _apply_fields(note, body.fields)
        note.tags = body.tags
        _check(note)
        col.add_note(note, body.deck_id)
        out = _note_out(note)
    sync.request_soon()
    return out


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: int, manager: CollectionManager = Depends(get_manager)):
    with manager.use() as col:
        return _note_out(_get_note(col, note_id))


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: int,
    body: NoteUpdate,
    identity: Identity = Depends(get_identity),
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    with manager.use() as col:
        note = _get_note(col, note_id)
        if identity.kind == "token":
            # un token write modifica solo le note che ha creato lui (tag agent::<nome>) e
            # non può toccare i tag riservati: né togliere `hub::bozza` né cambiare la provenienza
            if not (identity.agent and hub.is_own_note(note.tags, identity.agent)):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "Il token può modificare solo le note create da lui"
                )
            if body.tags is not None:
                body = body.model_copy(update={"tags": hub.merge_agent_tags(note.tags, body.tags)})
        if body.fields is not None:
            _apply_fields(note, body.fields)
        if body.tags is not None:
            note.tags = body.tags
        _check(note, allow_duplicate=True)
        col.update_note(note)
        out = _note_out(note)
    sync.request_soon()
    return out


@router.post("/notes/{note_id}/move", response_model=NoteOut)
def move_note(
    note_id: int,
    body: NoteMoveIn,
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    """Sposta tutte le carte della nota nel mazzo."""
    with manager.use() as col:
        try:
            note = hub.move_note(col, note_id, body.deck_id)
        except hub.HubError as e:
            raise hub_http_error(e)
        out = _note_out(note)
    sync.request_soon()
    return out


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(
    note_id: int,
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    """Cancella la nota con tutte le sue carte (la PWA chiede conferma prima)."""
    with manager.use() as col:
        try:
            hub.delete_note(col, note_id)
        except hub.HubError as e:
            raise hub_http_error(e)
    sync.request_soon()
    return Response(status_code=204)


@router.post("/notes/tags", response_model=NoteTagsOut)
def change_tags(
    body: NoteTagsIn,
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    """Aggiunge e/o toglie tag a più note in un colpo solo (un'unica voce di undo)."""
    with manager.use() as col:
        updated = hub.change_tags(col, body.note_ids, body.add, body.remove)
    if updated:
        sync.request_soon()
    return NoteTagsOut(updated=updated)
