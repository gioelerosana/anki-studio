# Anki PWA – backend

Backend FastAPI che tiene una copia della tua collezione Anki, la sincronizza
con **AnkiWeb** e la espone con un'API JSON pensata per una PWA su iPad.

Usa il pacchetto Python ufficiale `anki` (lo stesso motore di Anki desktop),
quindi scheduler (FSRS/SM-2), rendering dei template e sync sono quelli veri.

```
iPad (PWA) ──HTTPS──▶ FastAPI ──▶ collection.anki2 ◀──sync──▶ AnkiWeb ◀──▶ Anki desktop / AnkiMobile
```

## Avvio

In produzione gira dentro lo stack Docker alla radice del repo (`docker compose up -d --build`,
vedi il README principale). In sviluppo:

```bash
cd backend
uv venv && uv pip install -e ".[dev]"
ANKI_API_TOKEN=un-token-lungo-almeno-16 ANKI_DATA_DIR=./data \
  .venv/bin/uvicorn app.main:create_app --factory --reload --port 8000
```

> **Sempre un solo worker.** La collezione deve essere aperta da un unico processo.

Documentazione interattiva: `http://localhost:8000/docs`

## Primo collegamento ad AnkiWeb

```bash
TOKEN=...   # quello del .env
curl -X POST localhost:8000/api/sync/login -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"username":"tu@mail.it","password":"..."}'
curl -X POST localhost:8000/api/sync -H "Authorization: Bearer $TOKEN"
```

- La password **non viene salvata**: resta solo la chiave di sessione in `data/sync_auth.json` (permessi 600).
- Alla prima sync il server ha una collezione vuota, quindi scarica tutto da AnkiWeb (`full_download`), media compresi. I media si scaricano in background: puoi seguire l'avanzamento con `GET /api/sync`.
- Poi la sync parte da sola all'avvio, ogni `ANKI_AUTO_SYNC_MINUTES` minuti e allo spegnimento. La PWA può forzarla con `POST /api/sync`, ad esempio a fine sessione.
- Se server e AnkiWeb sono divergenti in modo inconciliabile (es. hai cambiato un tipo di nota su desktop senza sincronizzare), `POST /api/sync` risponde **409**. A quel punto la PWA deve chiedere quale versione tenere e chiamare `POST /api/sync/full` con `{"direction":"download"}` (vince AnkiWeb) oppure `{"direction":"upload"}` (vince il server).

## HTTPS per l'iPad

Una PWA installata su iPad richiede HTTPS. In produzione lo fornisce il Traefik dello stack; per i test:

- **Tailscale** (consigliato, nessuna porta aperta su internet):
  `tailscale serve --bg 8080` (porta di `web` nello stack) → `https://<macchina>.<tailnet>.ts.net`

Nello stack la PWA e l'API stanno **sulla stessa origine**: nginx (`apps/web/nginx.conf`)
serve i file statici e inoltra `/api` a questo servizio. Così non serve CORS e il cookie
per i media funziona senza problemi. Solo se servi la PWA da un'altra origine va aggiunta in
`ANKI_CORS_ORIGINS`.

## API

Tutte le rotte `/api/*` (tranne `/api/health`) richiedono `Authorization: Bearer <ANKI_API_TOKEN>`.

| Metodo | Rotta | Cosa fa |
|---|---|---|
| GET | `/api/decks` | Albero dei mazzi con conteggi nuove/in apprendimento/da ripassare |
| GET | `/api/stats/today` | Review di oggi, tempo, "Di nuovo" |
| GET | `/api/decks/{id}/study` | Prossima carta del mazzo (`done: true` se hai finito) |
| POST | `/api/decks/{id}/study/answer` | `{card_id, rating: 1-4, time_taken_ms}`, restituisce già la carta successiva |
| POST | `/api/decks/{id}/study/undo` | Annulla l'ultima risposta |
| POST | `/api/cards/{id}/bury` · `/suspend` | Seppellisci / sospendi |
| POST | `/api/cards/{id}/flag` | `{flag: 0-7}` |
| GET | `/api/notetypes` | Tipi di nota con i loro campi |
| POST | `/api/notes` | Crea nota `{deck_id, notetype_id, fields: {Front: …}, tags}` |
| GET/PATCH | `/api/notes/{id}` | Leggi / modifica campi e tag |
| GET | `/api/media/{file}` | Immagini e audio delle carte |
| POST | `/api/auth/session` | Imposta il cookie per i media (vedi sotto) |
| GET | `/api/sync` | Stato login, ultima sync, avanzamento media |
| POST | `/api/sync/login` · `/logout` | Collega o scollega AnkiWeb |
| POST | `/api/sync` | Sync normale (409 = serve la sync completa) |
| POST | `/api/sync/full` | `{direction: "upload" \| "download"}` |

### Note per la PWA

- **Carta**: `question_html` / `answer_html` vanno inseriti dentro
  `<div class="{card_class}">`, con lo `css` del tipo di nota in uno `<style>`.
  Meglio usare uno Shadow DOM o un iframe, così il CSS della carta non tocca il resto dell'app.
- **Media**: gli `src` sono già riscritti in `/api/media/...`. I tag `<img>` non
  possono inviare header, quindi all'avvio la PWA chiama una volta `POST /api/auth/session`
  e da lì il browser invia il cookie da solo.
- **Audio**: i `[sound:…]` diventano `<button class="anki-play" data-side="q|a" data-index="N">`.
  `question_av[N]` / `answer_av[N]` contengono l'URL del file oppure il testo da leggere con TTS
  (`speechSynthesis`). `autoplay` indica se riprodurli subito.
- **Pulsanti**: `button_labels` contiene gli intervalli dei 4 pulsanti, es. `["<1m","6m","10m","4g"]`.
- **Tempo**: misura sul client quanto ci metti a rispondere e invialo in `time_taken_ms`.
  Il server lo limita al massimo impostato nel preset del mazzo, come fa Anki desktop.
- Un **409** su `answer` significa che la coda è cambiata, per esempio dopo una sync: basta ricaricare `GET /study`.

## Test

```bash
.venv/bin/python -m pytest -q
```
