import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from .. import hub
from ..collection import CollectionManager
from ..deps import get_manager, get_sync
from ..schemas import MediaIn, MediaOut
from ..sync import SyncService
from .hub import hub_http_error

# niente dipendenze qui: require_auth la aggiunge main.py, come per le altre rotte.
# <img> e <audio> delle carte mandano da soli il cookie di sessione (stessa origine).
router = APIRouter(tags=["media"])


@router.get("/media/{filename}")
def get_media(filename: str, manager: CollectionManager = Depends(get_manager)):
    # Anki tiene tutti i media in una cartella piatta: niente sottocartelle né path traversal.
    if os.path.basename(filename) != filename or filename.startswith("."):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nome file non valido")
    with manager.use() as col:
        media_dir = Path(col.media.dir())
    path = media_dir / filename
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File non trovato")
    # i nomi dei media cambiano se cambia il contenuto: si può cache-are a lungo
    return FileResponse(path, headers={"Cache-Control": "private, max-age=604800"})


@router.post("/media", response_model=MediaOut, status_code=201)
def add_media(
    body: MediaIn,
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    """Carica un'immagine, un audio o un video breve (base64, al massimo 10 MB) nella cartella
    media. Estensione e contenuto devono coincidere; il nome si sanifica e Anki può cambiarlo
    se esiste già un file diverso: usa quello restituito nei campi (`<img src="…">`,
    `[sound:…]`). Per i token serve lo scope `write`."""
    with manager.use() as col:
        try:
            out = hub.add_media(col, body.filename, body.data_base64)
        except hub.HubError as e:
            raise hub_http_error(e)
    sync.request_soon()
    return out
