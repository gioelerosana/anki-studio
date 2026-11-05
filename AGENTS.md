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
- `docker-compose.yml` — `api` + `web` (nginx serve la PWA e inoltra `/api`, stessa origine).
  Il reverse proxy HTTPS (Traefik) **non** è in questo repo: vive nello stack principale.

## Regole non negoziabili

1. **Nessun dato perso.** Non sovrascrivere mai la collezione AnkiWeb o quella del server
   senza una scelta esplicita dell'utente (`/sync/full` solo dopo conferma in UI).
2. **Segreti fuori dal repo.** `.env`, `data/`, `backend/data/` sono ignorati. Mai
   loggare password AnkiWeb, `hkey` o `ANKI_API_TOKEN`.
3. **Il contenuto delle carte è isolato** (Shadow DOM o iframe): il CSS dei tipi di nota
   non tocca l'app e viceversa. L'HTML delle carte viene dalla collezione dell'utente:
   non eseguire script delle carte nel contesto dell'app.
4. **Lo scheduler è quello di Anki.** Niente calcoli di intervalli lato client.

## Controlli prima di ogni commit

```bash
pnpm typecheck && pnpm build      # frontend
pnpm test:api                     # backend (pytest)
```

Commit piccoli in stile Conventional Commits, in italiano, con lo scope dell'area:
`feat(web): …`, `fix(api): …`, `docs: …`. Fai `git add` **solo dei file della tua area**:
più agenti lavorano in parallelo sullo stesso checkout (web in `apps/web` e
`packages/ui-kit`, backend in `backend/`). Se devi toccare l'area dell'altro (es. il
contratto API), scrivilo nel messaggio di commit e aggiorna sia `schemas.py` sia `types.ts`.

## Roadmap

**Web (`apps/web`)**
- [x] Collegamento con token, elenco mazzi, sync manuale
- [x] Studio a tutto schermo: carta isolata, tap per girare, 4 pulsanti, tastiera (Spazio, 1–4), undo
- [x] Audio e TTS (`question_av`/`answer_av`, `autoplay`), pulsanti `.anki-play`
- [x] Azioni sulla carta: seppellisci, sospendi, flag, modifica nota
- [x] Aggiunta carte (tipo di nota, mazzo, campi, tag)
- [x] Stato sync: login AnkiWeb, avanzamento media, conflitto full sync con conferma
- [x] Impostazioni (tema, riduci animazioni, scollega) e statistiche di oggi
- [ ] Test su iPad reale come PWA installata (offline della shell, safe area, tastiera)
- [ ] Risposta scritta `{{type:…}}` e altre richieste al backend in [`docs/REQUESTS-WEB-TO-API.md`](docs/REQUESTS-WEB-TO-API.md)

**Backend (`backend`)**
- [x] Sync AnkiWeb (normale, full, media), studio, note, media, token
- [ ] Test della sync contro un server di sync locale (`anki` include un sync server) invece che AnkiWeb
- [ ] Robustezza: sync in background senza bloccare lo studio, retry, stato "sync in corso"
- [ ] Endpoint mancanti per la PWA (es. ricerca/browser, statistiche, opzioni mazzo)
- [ ] Sicurezza: rate limit sul login, header di sicurezza, log senza segreti
- [ ] Healthcheck significativo, logging strutturato, backup del volume dati
