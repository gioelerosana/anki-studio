"""La PWA servita dallo stesso processo dell'API.

Nell'immagine Docker unica non c'è nginx: FastAPI serve anche i file della build di
`apps/web` (`ANKI_WEB_DIR`). Stessa origine per PWA e API, quindi niente CORS e il cookie
dei media (`Path=/api/media`, `SameSite=Strict`) continua a funzionare. Un secondo
processo (nginx, Caddy) avrebbe voluto dire un supervisore nel container; uvicorn con un
solo worker basta: i file sono pochi, li legge `FileResponse` in un thread e davanti nello
stack c'è comunque Traefik con la compressione.

Le regole sono quelle che prima stavano in `apps/web/nginx.conf`:

- `/assets/*`: nome con l'hash del contenuto, cache di un anno `immutable`. Un asset che non
  esiste è un 404 vero: restituire `index.html` al posto di un chunk JS lo farebbe mettere
  in cache dal service worker come se fosse codice.
- `index.html`, `sw.js`, `manifest.webmanifest` e il resto: `no-cache`, così una versione
  nuova arriva alla prima apertura (il browser rivalida con l'ETag e riceve 304).
- Fallback SPA: ogni altra rotta in GET restituisce `index.html`.
- `/api/*` non passa mai di qui: una rotta API che non esiste è un 404 JSON, mai la PWA, e
  le risposte API restano `no-store` (vedi `security.security_headers`).
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"

_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def inline_script_hashes(index_html: str) -> list[str]:
    """Hash CSP degli script inline di index.html (il gestore d'errore che mostra a video
    perché l'app non parte, utile su iPad dove non c'è console)."""
    out = []
    for body in _INLINE_SCRIPT.findall(index_html):
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        out.append(f"'sha256-{digest}'")
    return out


def app_csp(index_html: str) -> str:
    """CSP della shell: blocca gli script che non vengono dall'app.

    L'HTML delle carte è già sanificato (`cardContent.ts` toglie `<script>` e gli `on*=`):
    `script-src` è la seconda linea di difesa, perché un handler inline sopravvissuto
    girerebbe con il token dell'app. Immagini, font e stili restano liberi di proposito:
    le carte della collezione possono usare immagini remote, `@font-face` e `style=`, e
    bloccarli romperebbe carte che su Anki desktop funzionano.
    """
    scripts = " ".join(["'self'", *inline_script_hashes(index_html)])
    return (
        f"script-src {scripts}; worker-src 'self'; object-src 'none'; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )


class PWAFiles(StaticFiles):
    """StaticFiles con le regole di cache di nginx e il fallback su index.html."""

    def __init__(self, directory: Path) -> None:
        super().__init__(directory=directory, html=False, check_dir=True)
        index = Path(directory) / "index.html"
        if not index.is_file():
            raise RuntimeError(f"{index} non esiste: la PWA non è stata compilata?")
        self.csp = app_csp(index.read_text(encoding="utf-8"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            route = scope["path"]
            if route == "/api" or route.startswith("/api/"):
                # arriva qui solo una rotta API che non esiste: 404 JSON di FastAPI
                raise HTTPException(status_code=404)
        await super().__call__(scope, receive, send)

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
            served = path
        except HTTPException as exc:
            if exc.status_code != 404 or path == "assets" or path.startswith("assets/"):
                raise
            response = await super().get_response("index.html", scope)
            served = "index.html"
        is_asset = served.startswith("assets/")
        response.headers["Cache-Control"] = IMMUTABLE if is_asset else NO_CACHE
        if served == "index.html":
            response.headers["Content-Security-Policy"] = self.csp
        return response


def pwa_app(directory: Path | None):
    """L'app ASGI che serve la PWA, oppure None se non c'è una build (sviluppo: la PWA
    la serve Vite su :5173 con il proxy verso questa API)."""
    if directory is None:
        return None
    # se ANKI_WEB_DIR è impostata e la build manca è un'immagine rotta: meglio non partire
    # (healthcheck rosso) che servire un'API senza app
    return PWAFiles(directory)
