# Anki Studio

PWA per **iPad** per studiare le flashcard **Anki** con un'interfaccia minimale,
sincronizzata con **AnkiWeb**. È sorella di [XMap Studio](https://github.com/gioelerosana/xmap-studio):
stesso design system e stesso stack frontend.

```
iPad (PWA) ──HTTPS──▶ Traefik ──▶ anki-studio (un container, un processo)
                                   ├─ /        PWA (file statici)
                                   └─ /api/*   FastAPI + motore Anki ──▶ collection.anki2 ◀──sync──▶ AnkiWeb
```

| Cartella | Cosa c'è |
|---|---|
| `apps/web` | PWA React 19 + Vite + Tailwind 3 |
| `packages/ui-kit` | Design system condiviso con XMap Studio ([docs/DESIGN-SYSTEM.md](docs/DESIGN-SYSTEM.md)) |
| `backend` | API FastAPI sul pacchetto Python ufficiale `anki` ([backend/README.md](backend/README.md)) |
| `Dockerfile` | L'immagine unica: build della PWA + runtime Python che serve PWA e API |
| `.github/workflows/ci.yml` | CI su PR e push, pubblicazione su GHCR ai tag `vX.Y.Z` |
| `deploy/stack` | Proposta di integrazione nello stack di myserv ([deploy/stack/README.md](deploy/stack/README.md)) |
| `scripts/smoke-test-image.sh` | Avvio di prova di un'immagine con l'hardening di produzione |

## L'immagine Docker

Un'unica immagine, `ghcr.io/gioelerosana/anki-studio`, per `linux/amd64` e `linux/arm64`. Dentro
c'è un solo processo: uvicorn con **un worker** (la collezione Anki va aperta da un unico
processo), che serve anche la PWA sulla stessa origine dell'API, così non serve CORS e il
cookie di sessione funziona. Le regole che prima stavano in nginx sono in `backend/app/web.py`:
cache di un anno per `/assets/*`, `no-cache` per `index.html`, `sw.js` e
`manifest.webmanifest`, fallback SPA, `/api/*` mai in cache e mai sostituito dalla PWA,
header di sicurezza, limite di 50 MB al body.

| | |
|---|---|
| Porta | `8000` |
| Dati | `/data` (collezione, media, backup `.colpkg`, chiave di sync AnkiWeb) |
| Utente | `1000:1000`, mai root; la cartella dati va data a questo UID |
| Filesystem | compatibile con `read_only: true` + tmpfs su `/tmp` |
| Healthcheck | nell'immagine: `GET /api/health` (200 anche durante una sync) |
| Spegnimento | `SIGTERM` → ultima sync e chiusura della collezione: concedi **120 s** (`stop_grace_period: 120s`) |
| Accesso | login con Authentik (OIDC): `ANKI_PUBLIC_URL`, `ANKI_OIDC_ISSUER`, `ANKI_OIDC_CLIENT_ID`, `ANKI_OIDC_CLIENT_SECRET_FILE=/run/secrets/…` (Docker secret). Nessun token da inserire nella PWA |
| Versione | label OCI `org.opencontainers.image.version` e `GET /api/health` → `version`, `revision` |

Le altre variabili sono in [backend/README.md](backend/README.md#configurazione).

### In locale o per un deploy di prova

```bash
cp .env.example .env     # imposta ANKI_PUBLIC_URL e le variabili ANKI_OIDC_*
docker compose up -d --build
```

Il login passa da Authentik anche qui: al provider va aggiunta la redirect URI
`<ANKI_PUBLIC_URL>/api/auth/callback` dell'origine di prova (per esempio quella `*.ts.net`),
accanto a quella di produzione. Come configurare il provider: [deploy/stack/README.md](deploy/stack/README.md#2-authentik).

- La PWA risponde su `http://127.0.0.1:8080`. Per provarla su iPad serve HTTPS, per esempio
  `tailscale serve --bg 8080`.
- I dati stanno nel volume `anki-studio_anki-data`. Backup e ripristino: [backend/README.md](backend/README.md#backup-e-ripristino).
- Su myserv il daemon ha `"bridge": "none"`: la build ha rete solo con `--network host`, quindi
  serve un `docker-compose.override.yml` (ignorato da git) con
  `services: {anki-studio: {build: {network: host}}}`, oppure
  `docker build --network host -t anki-studio:local .`.
- Avvio di prova di un'immagine qualsiasi, con `read_only`, `cap_drop: ALL` e i segreti come
  Docker secret, su una rete e un volume usa e getta: `scripts/smoke-test-image.sh anki-studio:local`.

**Aggiornare il deploy di prova di `/home/ubuntu/anki-studio`** a questa struttura: il
servizio ora si chiama `anki-studio` (prima `api` + `web`) ma il volume resta
`anki-studio_anki-data`, quindi i dati restano. Aggiorna anche l'override locale, poi
`docker compose up -d --build --remove-orphans` (lo stop del vecchio `api` fa l'ultima sync).

### In produzione

Nello stack principale con l'immagine pubblicata e pinnata per digest: vedi
[deploy/stack/README.md](deploy/stack/README.md), che spiega anche come spostare lì i dati
del deploy di prova.

## Pubblicazione

La CI (`.github/workflows/ci.yml`) gira su ogni PR e push: typecheck e build della PWA, pytest,
build dell'immagine per amd64 e arm64 e avvio di prova. Quando arriva un tag `vX.Y.Z` pubblica
anche l'immagine su GHCR con i tag `X.Y.Z`, `X.Y`, `latest` e `sha-<commit>` (le pre-release
`vX.Y.Z-rc.N` hanno solo `X.Y.Z-rc.N` e `sha-…`: niente `latest`), con provenance e SBOM.
Usa solo il `GITHUB_TOKEN` del workflow: nessun segreto da configurare.

La versione viene dal tag: PWA (Impostazioni), `/api/health` e label dell'immagine la
prendono da lì, non serve cambiarla nei `package.json`.

### Numerazione

Versioni nel formato `AA.V.M`, con tag `vAA.V.M`:

- `AA`: anno a due cifre (`26` = 2026);
- `V`: versione dell'app nell'anno (parte da `0`; sale quando cambia qualcosa di grosso);
- `M`: release minore, da `1` (la prima è **26.0.1**).

Rispetta `vX.Y.Z`, quindi la CI e lo script di update funzionano senza modifiche. Le
pre-release sono `vAA.V.M-rc.N`.

### Pubblicare una release

1. Porta il lavoro su `main` (la CI gira su `main`, sulle PR e sui tag) e controlla che il
   workflow **CI** sia verde su Actions.
2. Tagga `main` e fai push del tag:
   ```bash
   git tag -a v26.0.1 -m "Anki Studio 26.0.1"
   git push origin v26.0.1
   ```
   Il job **Pubblica su GHCR** scrive nel riepilogo il riferimento da pinnare,
   `ghcr.io/gioelerosana/anki-studio:26.0.1@sha256:…`.
3. **Visibilità del package** (solo la prima volta). Un package nuovo su GHCR nasce privato.
   - *Pubblico* (più semplice, il codice non contiene segreti): GitHub → il tuo profilo →
     Packages → `anki-studio` → Package settings → Change visibility → Public.
   - *Privato*: sul server serve un login a GHCR con un personal access token (classic) con il
     solo scope `read:packages`:
     ```bash
     docker login ghcr.io -u gioelerosana    # incolla il token come password
     ```
     Docker salva la credenziale in `~/.docker/config.json`: tienila con permessi 600.
   In entrambi i casi, nelle Package settings collega il package al repository
   (di solito lo fa da sé grazie alla label `org.opencontainers.image.source`).
4. **Digest e pin nello stack**. Il riferimento completo è nel riepilogo del workflow; in
   alternativa, dal server:
   ```bash
   docker buildx imagetools inspect ghcr.io/gioelerosana/anki-studio:26.0.1 | sed -n 3p   # Digest: sha256:…
   ```
   È il digest dell'indice multi-arch (vale per arm64 e amd64). Va scritto come
   `ghcr.io/gioelerosana/anki-studio:26.0.1@sha256:…` in `COMPOSE/compose.anki-studio.yml` dello stack,
   poi `task validate`: il resto è in [deploy/stack/README.md](deploy/stack/README.md).

Per le release successive basta un nuovo tag (`v26.0.2`, …) e aggiornare il pin nello stack a
mano, oppure lasciar fare a `scripts/update-anki-studio.sh` se hai attivato l'auto-update
controllato. Per verificare cosa è stato pubblicato:
`docker buildx imagetools inspect ghcr.io/gioelerosana/anki-studio:26.0.1 --format '{{json .Provenance}}'`.

Dependabot (`.github/dependabot.yml`) propone come PR gli aggiornamenti delle action e delle
immagini base, entrambe pinnate per digest. Le dipendenze Python sono fissate con gli hash in
`backend/requirements.lock`: dopo un cambio in `backend/pyproject.toml` rigeneralo con il
comando scritto in cima al file.

## Sviluppo

```bash
pnpm install
cd backend && uv venv && uv pip install -e ".[dev]" && cd ..

# terminale 1: API su :8000 (dati in backend/data)
# ANKI_DEV_LOGIN: niente Authentik in sviluppo, la PWA entra subito come "Sviluppo"
ANKI_DEV_LOGIN=true ANKI_DATA_DIR=./data pnpm dev:api
# terminale 2: PWA su :5173, con /api inoltrato a :8000
pnpm dev
```

Controlli: `pnpm typecheck`, `pnpm build`, `pnpm test:api`. Per l'immagine:
`docker build --network host -t anki-studio:local . && scripts/smoke-test-image.sh anki-studio:local`.

In sviluppo l'API gira senza `ANKI_WEB_DIR`, quindi serve solo `/api` (e la documentazione
interattiva su `http://localhost:8000/docs`); la PWA la serve Vite con il proxy verso `/api`.
