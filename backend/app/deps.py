from fastapi import Request

from .collection import CollectionManager
from .journal import Journal
from .security import Identity
from .sync import SyncService


def get_manager(request: Request) -> CollectionManager:
    return request.app.state.manager


def get_sync(request: Request) -> SyncService:
    return request.app.state.sync


def get_journal(request: Request) -> Journal:
    return request.app.state.journal


def get_identity(request: Request) -> Identity:
    """Chi sta chiamando, già verificato da require_auth (dipendenza di tutti i router)."""
    return request.state.identity
