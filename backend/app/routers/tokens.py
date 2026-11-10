"""Gestione dei token per gli agenti (docs/PIANO-HUB.md). Solo da sessione (o dal
vecchio ANKI_API_TOKEN): i token con scope non vedono queste rotte, vedi `app/security.py`."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..schemas import TokenCreated, TokenIn, TokenOut, TokenUpdate
from ..tokens import StoredToken, TokenError, TokenNameTaken, TokenStore

router = APIRouter(prefix="/tokens", tags=["tokens"])


def get_store(request: Request) -> TokenStore:
    return request.app.state.tokens


def _out(t: StoredToken) -> TokenOut:
    return TokenOut(
        id=t.id,
        name=t.name,
        scope=t.scope,
        review=t.review,
        created_at=t.created_at,
        last_used_at=t.last_used_at,
    )


@router.get("", response_model=list[TokenOut])
def list_tokens(store: TokenStore = Depends(get_store)):
    return [_out(t) for t in store.all()]


@router.post("", response_model=TokenCreated, status_code=201)
def create_token(body: TokenIn, store: TokenStore = Depends(get_store)):
    """Il token in chiaro è nella risposta e solo qui: sul server resta l'hash."""
    try:
        token, plain = store.create(body.name, body.scope, body.review)
    except TokenNameTaken as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    except TokenError as e:
        raise HTTPException(422, str(e))
    return TokenCreated(**_out(token).model_dump(), token=plain)


@router.patch("/{token_id}", response_model=TokenOut)
def update_token(token_id: str, body: TokenUpdate, store: TokenStore = Depends(get_store)):
    token = store.update(token_id, scope=body.scope, review=body.review)
    if token is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token non trovato")
    return _out(token)


@router.delete("/{token_id}", status_code=204)
def revoke_token(token_id: str, store: TokenStore = Depends(get_store)):
    if not store.revoke(token_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token non trovato")
    return Response(status_code=204)
