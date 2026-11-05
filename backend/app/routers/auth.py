from fastapi import APIRouter, Depends, Request, Response

from ..config import Settings, get_settings
from ..security import COOKIE_NAME, media_cookie_value, require_token

router = APIRouter(prefix="/auth", tags=["auth"])

_LEGACY_COOKIE = "anki_token"  # versione 0.1: conteneva il token stesso


def _secure(request: Request) -> bool:
    # su http://localhost (sviluppo) Safari scarterebbe un cookie Secure;
    # dietro Traefik lo schema arriva come https grazie a --proxy-headers
    return not (
        request.url.scheme == "http" and request.url.hostname in ("localhost", "127.0.0.1")
    )


@router.post("/session", status_code=204, dependencies=[Depends(require_token)])
def create_session(
    request: Request, response: Response, settings: Settings = Depends(get_settings)
):
    """Imposta il cookie usato dal browser per caricare immagini e audio delle carte.

    Il cookie vale solo per GET /api/media/*: non contiene il token e non
    autorizza nessun'altra rotta.
    """
    response.set_cookie(
        COOKIE_NAME,
        media_cookie_value(settings),
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        secure=_secure(request),
        samesite="strict",
        path="/api/media",
    )
    response.delete_cookie(_LEGACY_COOKIE, path="/api")


@router.delete("/session", status_code=204)
def delete_session(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/api/media")
    response.delete_cookie(_LEGACY_COOKIE, path="/api")
