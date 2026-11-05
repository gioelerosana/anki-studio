from fastapi import Request

from .collection import CollectionManager
from .sync import SyncService


def get_manager(request: Request) -> CollectionManager:
    return request.app.state.manager


def get_sync(request: Request) -> SyncService:
    return request.app.state.sync
