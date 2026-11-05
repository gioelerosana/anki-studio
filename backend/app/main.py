import asyncio
import logging
import random
import time
from contextlib import asynccontextmanager, suppress

import anki.lang
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.body_limit import RequestBodyLimitMiddleware

from .collection import CollectionBusy, CollectionManager
from .config import Settings, get_settings
from .logging_setup import register_secret, setup_logging
from .routers import auth, browse, decks, media, notes, study, sync
from .security import RateLimiter, require_token, security_headers
from .sync import SyncService, next_auto_delay
from .web import pwa_app

log = logging.getLogger("anki_studio")

# Allo spegnimento: 30 s di uvicorn per le richieste in corso (--timeout-graceful-shutdown),
# fino a 30 s per la sync in corso, 15 s per l'ultima sync, poi la chiusura. Docker deve
# concedere almeno 120 s prima del SIGKILL (stop_grace_period nei file compose).
_SHUTDOWN_WAIT_S = 30
_SHUTDOWN_SYNC_TIMEOUT_S = 15

# Come client_max_body_size di nginx: il body viene letto prima del controllo del token,
# quindi senza limite chiunque potrebbe riempire la memoria con una richiesta enorme.
MAX_BODY_BYTES = 50 * 1024 * 1024


async def _background_sync(app: FastAPI, settings: Settings) -> None:
    """Login automatico, sync all'avvio e poi ogni N minuti, con backoff sugli errori."""
    service: SyncService = app.state.sync
    interval = settings.anki_auto_sync_minutes * 60

    if not service.logged_in and settings.ankiweb_username and settings.ankiweb_password:
        try:
            await run_in_threadpool(
                service.login, settings.ankiweb_username, settings.ankiweb_password
            )
        except Exception as e:  # noqa: BLE001 - l'API deve partire comunque
            log.warning("Login automatico fallito: %s", e)

    with suppress(Exception):
        # backup periodico con la rotazione di Anki (salta se è troppo presto)
        await run_in_threadpool(service.backup, force=False)

    delay = 0.0 if settings.anki_sync_on_startup else interval
    failures = 0
    while True:
        service.next_auto_sync_at = time.time() + delay
        await asyncio.sleep(delay)
        result = None
        if service.logged_in:
            result = await run_in_threadpool(service.sync, wait=False, quick=True)
            if result is not None:
                log.info(
                    "Sync automatica",
                    extra={"outcome": str(result.outcome), "error_kind": str(result.error_kind)},
                )
        if interval <= 0:
            service.next_auto_sync_at = None
            return
        delay, failures = next_auto_delay(result, failures, interval)
        service.auto_failures = failures
        if failures:
            delay *= random.uniform(0.8, 1.2)  # jitter: niente raffiche sincronizzate
        with suppress(Exception):
            await run_in_threadpool(service.backup, force=False)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.anki_log_format, settings.anki_log_level)
    register_secret(settings.anki_api_token)
    register_secret(settings.ankiweb_password)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # va impostata prima di aprire la collezione: il backend Rust la legge allora
        anki.lang.set_lang(settings.anki_lang)
        manager = CollectionManager(
            settings.collection_path, busy_timeout=settings.anki_busy_timeout
        )
        manager.open()
        service = SyncService(
            manager,
            settings.sync_auth_path,
            endpoint=settings.anki_sync_endpoint,
            backup_dir=settings.backup_dir,
            io_timeout_secs=settings.anki_sync_io_timeout,
        )
        app.state.manager = manager
        app.state.sync = service
        log.info(
            "Collezione aperta",
            extra={"server": service.endpoint or "ankiweb", "logged_in": service.logged_in},
        )

        task = None
        if settings.anki_sync_on_startup or settings.anki_auto_sync_minutes > 0:
            # in background: l'API risponde subito anche se AnkiWeb è lento o irraggiungibile
            task = asyncio.create_task(_background_sync(app, settings))
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            # una sync partita prima dello spegnimento continua nel suo thread: la aspettiamo
            idle = await run_in_threadpool(service.wait_idle, _SHUTDOWN_WAIT_S)
            if not idle:
                log.warning("Sync ancora in corso allo spegnimento: chiudo dopo che finisce")
            elif service.logged_in and not service.full_sync_required:
                # ultima sync per non lasciare review solo sul server
                result = await run_in_threadpool(
                    service.sync, quick=True, io_timeout_secs=_SHUTDOWN_SYNC_TIMEOUT_S
                )
                log.info("Sync allo spegnimento", extra={"outcome": str(result.outcome)})
            # close() prende il lock: se una sync è ancora attiva aspetta che finisca,
            # così la collezione non viene mai chiusa a metà scrittura
            await run_in_threadpool(manager.close)
            log.info("Collezione chiusa")

    web = pwa_app(settings.anki_web_dir)
    # con la PWA sulla stessa origine /docs sarebbe pubblico: la documentazione interattiva
    # resta solo in sviluppo, quando l'API gira da sola (nginx prima inoltrava solo /api)
    docs = web is None
    app = FastAPI(
        title="Anki Studio API",
        version=settings.anki_studio_version,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.token_limiter = RateLimiter(
        settings.anki_token_max_failures, settings.anki_token_window_s
    )
    app.state.login_limiter = RateLimiter(
        settings.anki_login_max_failures, settings.anki_login_window_s
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=MAX_BODY_BYTES)

    access = logging.getLogger("anki_studio.access")

    @app.middleware("http")
    async def _headers_and_log(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        security_headers(request, response.headers)
        path = request.url.path
        # health e file statici riuscito sono rumore: in DEBUG
        quiet = path == "/api/health" or (
            not path.startswith("/api/") and response.status_code in (200, 304)
        )
        level = logging.DEBUG if quiet else logging.INFO
        # solo il path: niente query string né header (dove viaggiano i token)
        access.log(
            level,
            "%s %s %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - start) * 1000, 1),
                "client": request.client.host if request.client else None,
            },
        )
        return response

    @app.exception_handler(CollectionBusy)
    async def _busy(request: Request, exc: CollectionBusy):
        running = getattr(request.app.state, "sync", None)
        detail = (
            "Sync in corso: riprova tra poco"
            if running is not None and running.running
            else "Collezione occupata: riprova tra poco"
        )
        return JSONResponse({"detail": detail}, status_code=503, headers={"Retry-After": "5"})

    @app.get("/api/health", tags=["system"])
    def health(request: Request):
        """Per Docker: 200 se la collezione è aperta e risponde (o è occupata da una sync)."""
        manager: CollectionManager | None = getattr(request.app.state, "manager", None)
        service: SyncService | None = getattr(request.app.state, "sync", None)
        syncing = service.running if service else None
        if manager is None or not manager.is_open:
            return JSONResponse({"ok": False, "collection": "closed"}, status_code=503)
        try:
            with manager.use(timeout=2) as col:
                col.db.scalar("select 1")
            state = "open"
        except CollectionBusy:
            # una full sync può tenere la collezione per minuti: non è un guasto,
            # e un riavvio del container a metà sarebbe la cosa peggiore
            state = "busy"
        except Exception:  # noqa: BLE001
            log.exception("Healthcheck: collezione non leggibile")
            return JSONResponse({"ok": False, "collection": "error"}, status_code=503)
        return {
            "ok": True,
            "collection": state,
            "syncing": syncing is not None,
            "version": settings.anki_studio_version,
            "revision": settings.anki_studio_revision or None,
        }

    protected = [Depends(require_token)]
    for r in (decks.router, study.router, notes.router, browse.router, sync.router):
        app.include_router(r, prefix="/api", dependencies=protected)
    # i media accettano anche il cookie, le sessioni gestiscono da sé l'autenticazione
    app.include_router(media.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    if web is not None:
        # La PWA è il "default" del router, non un Mount su "/": così entra in gioco solo
        # quando nessuna rotta corrisponde, e un metodo sbagliato su una rotta API resta 405.
        app.router.default = web
    return app


# avvio: uvicorn app.main:create_app --factory
