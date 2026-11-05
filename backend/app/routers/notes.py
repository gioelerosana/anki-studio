from fastapi import APIRouter, Depends, HTTPException, status

from anki.collection import Collection
from anki.consts import MODEL_CLOZE
from anki.notes import Note, NoteFieldsCheckResult

from ..collection import CollectionManager
from ..deps import get_manager
from ..schemas import NoteIn, NoteOut, Notetype, NotetypeField, NoteUpdate

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
def create_note(body: NoteIn, manager: CollectionManager = Depends(get_manager)):
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
        return _note_out(note)


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: int, manager: CollectionManager = Depends(get_manager)):
    with manager.use() as col:
        return _note_out(_get_note(col, note_id))


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: int, body: NoteUpdate, manager: CollectionManager = Depends(get_manager)
):
    with manager.use() as col:
        note = _get_note(col, note_id)
        if body.fields is not None:
            _apply_fields(note, body.fields)
        if body.tags is not None:
            note.tags = body.tags
        _check(note, allow_duplicate=True)
        col.update_note(note)
        return _note_out(note)
