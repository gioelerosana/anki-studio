import secrets

from fastapi import Depends, HTTPException, Request, status

from .config import Settings, get_settings

COOKIE_NAME = "anki_token"


def require_token(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Accetta il token da header Bearer oppure da cookie.

    Il cookie serve per i tag <img>/<audio> delle carte, che non possono
    mandare header: la PWA chiama POST /api/auth/session una volta e poi
    il browser lo invia da solo.
    """
    token = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.cookies.get(COOKIE_NAME)
    if not token or not secrets.compare_digest(token, settings.anki_api_token):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token mancante o non valido",
            headers={"WWW-Authenticate": "Bearer"},
        )
