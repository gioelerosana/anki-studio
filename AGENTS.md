# AGENTS.md — guida operativa

Istruzioni per gli agenti AI (e per chi contribuisce). Leggila prima di toccare il codice.

## Cos'è

**Anki Studio** è una PWA per iPad che fa da interfaccia minimale ad Anki.
Lo scheduling, il rendering delle carte e la sync **non si reimplementano**: li fa
il motore ufficiale di Anki (pacchetto Python `anki`) nel backend. La PWA mostra e
chiede, il backend decide.

È un'app sorella di **XMap Studio** (`/home/ubuntu/xmap-studio`): stesso design
system, stesse convenzioni (italiano, sentence case, commenti che spiegano il
*perché*), stessa cura per iPad (safe area, `coarse:`, niente zoom da doppio tap,
PWA con service worker che funziona alla prima apertura). Quando hai un dubbio su
come XMap Studio risolve una cosa, guarda là e fai lo stesso.

## Struttura

- `apps/web` — React 19 + Vite 6 + Tailwind 3 + lucide-react. TypeScript strict.
  - `src/api/client.ts`, `src/api/types.ts` — client tipizzato. **`types.ts` è lo
    specchio di `backend/app/schemas.py`**: se cambi l'uno, aggiorna l'altro.
  - `src/settings.ts` — preferenze per dispositivo (tema, token) in localStorage.
  - `src/screens/` — schermate.
  - `public/sw.js` — service worker: precache della shell e **mai** `/api/*`.
- `packages/ui-kit` — componenti e `theme.css` (copiati da XMap Studio). Regole in
  [`docs/DESIGN-SYSTEM.md`](docs/DESIGN-SYSTEM.md): mai colori letterali, un solo `primary` per vista.
- `backend` — FastAPI. Contratto API e note per il frontend in [`backend/README.md`](backend/README.md).
  - Un solo processo e un solo worker: la collezione è aperta una volta e protetta da un `RLock`.
  - Le rotte sono `def` (non `async`): girano nel threadpool e passano da `manager.use()`.
  - `app/web.py` — serve la build della PWA dallo stesso processo (`ANKI_WEB_DIR`): cache,
    fallback SPA, header. Sostituisce nginx: `/api/*` non passa mai di qui.
  - `requirements.lock` — dipendenze con hash per l'immagine e la CI (rigenerale con uv, vedi README).
- `Dockerfile` — **un'unica immagine** (PWA + API, un processo, utente 1000:1000, compatibile con
  `read_only`, healthcheck). Pubblicata su `ghcr.io/gioelerosana/anki-studio` da
  `.github/workflows/ci.yml` ai tag `vX.Y.Z`, per amd64 e arm64.
- `docker-compose.yml` — l'immagine unica in locale / deploy di prova. Il reverse proxy HTTPS
  (Traefik) **non** è in questo repo: vive nello stack principale.
- `deploy/stack/` — proposta di integrazione nello stack di myserv (compose, router Traefik,
  script di auto-update): la applica l'utente, mai un agente.
- `scripts/smoke-test-image.sh` — avvio di prova di un'immagine con l'hardening di produzione.

## Regole non negoziabili

1. **Nessun dato perso.** Non sovrascrivere mai la collezione AnkiWeb o quella del server
   senza una scelta esplicita dell'utente (`/sync/full` solo dopo conferma in UI).
2. **Segreti fuori dal repo.** `.env`, `data/`, `backend/data/` sono ignorati. Mai
   loggare password AnkiWeb, `hkey`, client secret OIDC o `ANKI_API_TOKEN`.
3. **Il contenuto delle carte è isolato** (Shadow DOM o iframe): il CSS dei tipi di nota
   non tocca l'app e viceversa. L'HTML delle carte viene dalla collezione dell'utente:
   non eseguire script delle carte nel contesto dell'app.
4. **Lo scheduler è quello di Anki.** Niente calcoli di intervalli lato client.
5. **Accesso solo con Authentik (OIDC).** La PWA non chiede né tiene token: il backend fa il
   login (client confidenziale, `app/oidc.py`) e la sessione è un cookie HttpOnly. Niente
   token in `localStorage`, niente bypass dell'accesso fuori da `ANKI_DEV_LOGIN` (solo sviluppo).

## Controlli prima di ogni commit

```bash
pnpm typecheck && pnpm build      # frontend
pnpm test:api                     # backend (pytest)
# se tocchi Dockerfile, app/web.py, dipendenze o deploy (su myserv la build vuole --network host):
docker build --network host -t anki-studio:local . && scripts/smoke-test-image.sh anki-studio:local
```

Su myserv gira anche un deploy di prova (progetto compose `anki-studio`, volume
`anki-studio_anki-data`, con dati veri): per le prove usa sempre un progetto compose, un
volume e una porta diversi (lo script di smoke test lo fa da sé).

Commit piccoli in stile Conventional Commits, in italiano, con lo scope dell'area:
`feat(web): …`, `fix(api): …`, `docs: …`. Fai `git add` **solo dei file della tua area**:
più agenti lavorano in parallelo sullo stesso checkout (web in `apps/web` e
`packages/ui-kit`, backend in `backend/`). Se devi toccare l'area dell'altro (es. il
contratto API), scrivilo nel messaggio di commit e aggiorna sia `schemas.py` sia `types.ts`.

## Dalla feature al server: procedura di rilascio

È il ciclo completo, nell'ordine. **Ogni passo che esce dalla macchina (push, merge, tag,
aggiornamento del server) aspetta il via esplicito dell'utente**: la prova (passo 2) è sua,
e il suo «ok» sblocca i passi 3–6.

1. **Feature** in un worktree/branch dedicato (`t3/<nome>`), con i controlli di sopra
   (`pnpm typecheck && pnpm build`, `pnpm test:api` se tocchi il backend).
2. **Prova in un ambiente di test servito via Tailscale**, che l'utente apre dal suo
   dispositivo (iPad, telefono). Mai sul deploy di prova `anki-studio` né sul server vero:
   dati, porte e progetto compose diversi.
   ```bash
   # dati di prova: lo script scrive in backend/data (ignorata da git)
   cd backend && .venv/bin/python scripts/seed_dev.py && cd ..
   # API con login di sviluppo (ANKI_DEV_LOGIN non è ammesso con ANKI_WEB_DIR) su una porta libera
   ANKI_DEV_LOGIN=true ANKI_DATA_DIR=$PWD/backend/data setsid nohup \
     backend/.venv/bin/uvicorn app.main:create_app --factory --app-dir backend --port 8010 >api.log 2>&1 </dev/null &
   # PWA con Vite (accetta già *.ts.net) e proxy verso quell'API
   API_URL=http://127.0.0.1:8010 pnpm --filter @anki-studio/web exec vite --port 5183 --strictPort &
   # esposizione sul tailnet, su una porta HTTPS che nessun altro serve (controlla `tailscale serve status`)
   tailscale serve --bg --https=9443 http://127.0.0.1:5183
   ```
   L'URL è `https://myserv.tail702c0b.ts.net:9443`. Verifica anche tu la feature (browser di
   anteprima) prima di chiamare l'utente. Non usare `pkill -f` con un pattern che compare nel
   tuo stesso comando: uccide la shell. **A prova finita** smonta tutto: `tailscale serve
   --https=9443 off`, ferma API e Vite, cancella i dati di prova.
3. **Incorporazione**: commit piccoli (Conventional Commits, in italiano, `git add` solo dei
   file dell'area), push del branch e **PR verso `main`** con `gh`. Collega la PR al thread e
   aspetta la CI verde (`gh pr checks`); poi merge, quando l'utente dice di procedere.
4. **Immagine**: la crea la CI al tag. Da `main` aggiornato scegli il numero successivo
   (`git tag --sort=-v:refname | head -1`; `vAA.V.M`, vedi README «Numerazione») e
   `git tag -a vX.Y.Z -m "Anki Studio X.Y.Z" && git push origin vX.Y.Z`. Aspetta il workflow
   **Pubblica su GHCR** (`gh run watch`) e leggi nel riepilogo il riferimento
   `ghcr.io/gioelerosana/anki-studio:X.Y.Z@sha256:…` (o
   `docker buildx imagetools inspect ghcr.io/gioelerosana/anki-studio:X.Y.Z`).
5. **Aggiornamento del server in un nuovo thread nel progetto `stack`** (`/home/ubuntu/stack`).
   Lo stack ha le sue regole (`AGENTS.md`, `docs/infrastructure/04-maintenance-updates.md`):
   non si tocca da qui. Crea il thread con `t3_thread_launch` (`projectId` del progetto
   *stack*, workspace `root`) e un prompt che contenga: versione e riferimento completo
   `tag@sha256:`, cosa cambia nella release, e il compito — *«aggiorna il pin in
   `COMPOSE/compose.anki-studio.yml`, `task validate`, `task updates:pull`,
   `docker compose up -d --no-deps anki-studio`, verifica healthcheck, `/api/health` (versione) e
   log; mantieni l'immagine precedente per il rollback; fai commit e push»*. Se l'utente ha
   attivo l'auto-update (`deploy/stack/scripts/update-anki-studio.sh`) il pin può farlo lui, ma
   il thread resta il modo per averlo subito e verificato.
6. **Chiusura**: riporta all'utente versione rilasciata, link PR e thread dello stack;
   aggiorna la Roadmap qui sotto se la feature chiude una voce.

## Roadmap

**Web (`apps/web`)**
- [x] Accesso con Authentik (OIDC) senza token da inserire, elenco mazzi, sync manuale
- [x] Studio a tutto schermo: carta isolata, tap per girare, 4 pulsanti, tastiera (Spazio, 1–4), undo
- [x] Audio e TTS (`question_av`/`answer_av`, `autoplay`), pulsanti `.anki-play`
- [x] Azioni sulla carta: seppellisci, sospendi, flag, modifica nota
- [x] Aggiunta carte (tipo di nota, mazzo, campi, tag)
- [x] Stato sync: login AnkiWeb, avanzamento media, conflitto full sync con conferma
- [x] Impostazioni (tema, riduci animazioni, scollega) e statistiche di oggi
- [x] Telecomando: il telefono sceglie il mazzo e comanda lo studio aperto sul computer (`#/remote`, WebSocket `/api/remote`)
- [ ] Telecomando provato su iPhone + computer veri (Wake Lock, riconnessione dopo lo standby)
- [ ] Test su iPad reale come PWA installata (offline della shell, safe area, tastiera)
- [ ] Risposta scritta `{{type:…}}` e altre richieste al backend in [`docs/REQUESTS-WEB-TO-API.md`](docs/REQUESTS-WEB-TO-API.md)

**Backend (`backend`)**
- [x] Sync AnkiWeb (normale, full, media), studio, note, media, token
- [x] Script di seed per lo sviluppo (`backend/scripts/seed_dev.py`)
- [x] Test della sync contro un server di sync locale (`tests/test_sync_e2e.py`, `ANKI_SYNC_ENDPOINT`)
- [x] Robustezza: sync in background senza bloccare lo studio, retry, stato "sync in corso"
- [x] Endpoint mancanti per la PWA (ricerca note, tag, statistiche, opzioni mazzo, risposta digitata)
- [x] Sicurezza: rate limit su token e login, header di sicurezza, log senza segreti, proxy headers
- [x] Login OIDC con Authentik (Authorization Code + PKCE, sessione in cookie HttpOnly, CSRF)
- [x] Healthcheck significativo, logging strutturato, backup automatici e del volume dati
- [ ] Prima sync con l'account AnkiWeb vero (istruzioni in `backend/README.md`)
- [ ] Caricamento di media dalla PWA (es. foto per una nota nuova)
- [ ] Modifica delle opzioni del mazzo dalla PWA (oggi sola lettura)

**Immagine e deploy**
- [x] Immagine Docker unica (PWA servita da FastAPI), multi-arch, hardening, versione in `/api/health`
- [x] CI su GitHub Actions e pubblicazione su GHCR ai tag `vX.Y.Z`
- [x] Proposta per lo stack (`deploy/stack/`) con script di auto-update controllato
- [x] Repository GitHub, primo tag (`v26.0.1`, numerazione `vAA.V.M`) e package GHCR pubblico — README, "Pubblicazione"
- [ ] Integrazione nello stack e migrazione dei dati dal deploy di prova (`deploy/stack/README.md`)
- [ ] Blueprint Authentik applicato (`deploy/stack/auth/blueprints/anki-studio-oidc.yaml`) e login
      provato sulla PWA installata su iPad
