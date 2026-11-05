import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from ..collection import CollectionManager
from ..deps import get_manager

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
