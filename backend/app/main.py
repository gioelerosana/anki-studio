import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from .collection import CollectionManager
from .config import Settings, get_settings
from .routers import auth, decks, media, notes, study, sync
from .security import require_token
from .sync import SyncService

log = logging.getLogger("anki_pwa")


async def _auto_sync_loop(service: SyncService, minutes: int) -> None:
    while True:
        await asyncio.sleep(minutes * 60)
        if service.logged_in:
            result = await run_in_threadpool(service.sync)
            log.info("Sync automatica: %s", result.outcome)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager = CollectionManager(settings.collection_path)
        manager.open()
        service = SyncService(manager, settings.sync_auth_path)
        app.state.manager = manager
        app.state.sync = service

        if not service.logged_in and settings.ankiweb_username and settings.ankiweb_password:
            await run_in_threadpool(
                service.login, settings.ankiweb_username, settings.ankiweb_password
            )
        if settings.anki_sync_on_startup and service.logged_in:
            result = await run_in_threadpool(service.sync)
            log.info("Sync all'avvio: %s %s", result.outcome, result.error or "")

        task = None
        if settings.anki_auto_sync_minutes > 0:
            task = asyncio.create_task(
                _auto_sync_loop(service, settings.anki_auto_sync_minutes)
            )
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            # ultima sync prima di spegnersi, per non perdere le review
            if service.logged_in:
                await run_in_threadpool(service.sync)
            manager.close()

    app = FastAPI(title="Anki PWA backend", version="0.1.0", lifespan=lifespan)
    app.dependency_overrides[get_settings] = lambda: settings

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/api/health", tags=["system"])
    def health():
        return {"ok": True}

    protected = [Depends(require_token)]
    for r in (decks.router, study.router, notes.router, media.router, sync.router):
        app.include_router(r, prefix="/api", dependencies=protected)
    app.include_router(auth.router, prefix="/api")
    return app


logging.basicConfig(level=logging.INFO)
# avvio: uvicorn app.main:create_app --factory
