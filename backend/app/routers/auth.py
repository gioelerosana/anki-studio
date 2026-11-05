from fastapi import APIRouter, Depends, Response

from ..config import Settings, get_settings
from ..security import COOKIE_NAME, require_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/session", status_code=204, dependencies=[Depends(require_token)])
def create_session(response: Response, settings: Settings = Depends(get_settings)):
    """Imposta il cookie usato dal browser per caricare immagini e audio delle carte."""
    response.set_cookie(
        COOKIE_NAME,
        settings.anki_api_token,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/api",
    )


@router.delete("/session", status_code=204)
def delete_session(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/api")
