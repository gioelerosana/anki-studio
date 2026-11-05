# syntax=docker/dockerfile:1
#
# Anki Studio: un'unica immagine con la PWA e l'API (FastAPI + motore ufficiale `anki`).
#
#   docker build -t anki-studio:local .                     # su myserv: --network host
#   docker run -p 127.0.0.1:8080:8000 -e ANKI_API_TOKEN=... -v anki-data:/data anki-studio:local
#
# Un solo processo, uvicorn con un solo worker: la collezione Anki va aperta da un unico
# processo, e lo stesso processo serve anche i file della PWA (app/web.py), sulla stessa
# origine dell'API. Niente nginx e niente supervisore.
#
# Le immagini base sono pinnate per digest (come tutto lo stack su myserv): Dependabot
# propone gli aggiornamenti (.github/dependabot.yml).

ARG NODE_IMAGE=node:22.23.4-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914
ARG PYTHON_IMAGE=python:3.13.18-slim-trixie@sha256:09a17cad02668ae61ece136b4fd36ac3849e14f670ebedb637ea3e15580525bc

# ---- PWA ---------------------------------------------------------------------
# La build della PWA è identica per ogni architettura: gira una volta sola, nativa
# ($BUILDPLATFORM), anche quando buildx costruisce arm64 su un runner amd64.
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS web
ARG VERSION=dev
WORKDIR /repo
# pnpm nella versione di "packageManager" in package.json
RUN corepack enable
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages/ui-kit/package.json packages/ui-kit/
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile
COPY packages packages
COPY apps/web apps/web
RUN APP_VERSION="${VERSION#v}" pnpm --filter @anki-studio/web build

# ---- runtime -----------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

# UID/GID fissi: la cartella dati sull'host (bind mount nello stack) va data a 1000:1000,
# e restano compatibili con il volume del primo deploy di prova.
ARG UID=1000
ARG GID=1000
RUN groupadd --system --gid ${GID} anki \
 && useradd --system --uid ${UID} --gid ${GID} --home-dir /nonexistent --no-create-home \
      --shell /usr/sbin/nologin anki

WORKDIR /srv
# Dipendenze con versioni e hash fissati (backend/requirements.lock, generato con uv):
# la build di oggi e quella tra sei mesi installano gli stessi file.
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir --no-compile --require-hashes -r requirements.lock \
 && python -m compileall -q "$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
 && rm requirements.lock

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY --from=web /repo/apps/web/dist ./web
RUN python -m compileall -q app scripts \
 && mkdir -p /data && chown ${UID}:${GID} /data && chmod 700 /data

ARG VERSION=dev
ARG REVISION=
ARG CREATED=
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # niente scritture fuori da /data e /tmp: l'immagine gira con read_only: true
    HOME=/tmp \
    ANKI_DATA_DIR=/data \
    ANKI_WEB_DIR=/srv/web \
    ANKI_LOG_FORMAT=json \
    ANKI_STUDIO_VERSION=${VERSION} \
    ANKI_STUDIO_REVISION=${REVISION} \
    # X-Forwarded-For/-Proto valgono solo se arrivano da un proxy della rete privata
    # (Traefik, tailscale serve via la porta pubblicata): così il rate limit vede l'IP
    # vero del client e un client non può fingersi un altro scrivendo l'header a mano.
    FORWARDED_ALLOW_IPS="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"

# In CI le label le scrive docker/metadata-action (con source e la descrizione del repo);
# queste valgono per le build locali.
LABEL org.opencontainers.image.title="Anki Studio" \
      org.opencontainers.image.description="PWA per iPad per studiare le flashcard Anki, sincronizzata con AnkiWeb" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}"

USER ${UID}:${GID}
VOLUME /data
EXPOSE 8000

# 200 anche durante una sync lunga ("busy"): un riavvio a metà sync sarebbe peggio.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

# SIGTERM: uvicorn chiude le connessioni (30 s per le richieste in corso), poi l'app aspetta
# la sync in corso, fa l'ultima sync e chiude la collezione. Chi avvia il container deve
# concedere almeno 120 s prima del SIGKILL (stop_grace_period: 120s, docker stop -t 120):
# il default di Docker (10 s) potrebbe interrompere la sync finale.
STOPSIGNAL SIGTERM

# --timeout-keep-alive 100: più dei 90 s per cui Traefik tiene aperta una connessione
#   inutilizzata verso il backend. Con il default di uvicorn (5 s) è uvicorn a chiuderla per
#   primo e una richiesta che parte in quell'istante riceve un 502.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--no-access-log", "--no-server-header", \
     "--timeout-graceful-shutdown", "30", "--timeout-keep-alive", "100"]
