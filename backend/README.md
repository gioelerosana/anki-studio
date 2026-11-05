# Anki Studio – backend

Backend FastAPI che tiene una copia della tua collezione Anki, la sincronizza
con **AnkiWeb** (o con un sync server self-hosted) e la espone con un'API JSON
pensata per una PWA su iPad.

Usa il pacchetto Python ufficiale `anki` (lo stesso motore di Anki desktop),
quindi scheduler (FSRS/SM-2), rendering dei template e sync sono quelli veri.

```
iPad (PWA) ──HTTPS──▶ Traefik ──▶ anki-studio: FastAPI (/api + file della PWA) ──▶ collection.anki2 ◀──sync──▶ AnkiWeb ◀──▶ Anki desktop / AnkiMobile
```

## Avvio

In produzione gira nell'immagine Docker unica (`Dockerfile` alla radice), che serve anche la PWA
dallo stesso processo (`app/web.py`, attivo quando `ANKI_WEB_DIR` è impostata): vedi il README
principale. In sviluppo:

```bash
cd backend
uv venv && uv pip install -e ".[dev]"
ANKI_API_TOKEN=un-token-lungo-almeno-16 ANKI_DATA_DIR=./data \
  .venv/bin/uvicorn app.main:create_app --factory --reload --port 8000
```

> **Sempre un solo worker.** La collezione deve essere aperta da un unico processo.

Documentazione interattiva: `http://localhost:8000/docs`, solo in sviluppo. Quando il processo
serve anche la PWA (`ANKI_WEB_DIR`, cioè nell'immagine) `/docs` e `/openapi.json` sono spenti:
sarebbero pubblici sulla stessa origine dell'app.

### Collezione di prova

Per sviluppare la PWA senza un account AnkiWeb:

```bash
.venv/bin/python scripts/seed_dev.py           # crea data/collection.anki2
.venv/bin/python scripts/seed_dev.py --force   # la ricrea (la vecchia va in data/backup-seed-*)
```

Contiene mazzi annidati (`Lingue::Spagnolo::Verbi`, `Lingue::Inglese::Phrasal verbs`,
`Scienze::Chimica`, un mazzo vuoto `Archivio`), Basic, Basic con inversa (anche facoltativa),
risposta da digitare, Cloze, un tipo di nota **Vocabolo** con CSS personalizzato (anche
`.nightMode`) e TTS nel template, immagini PNG/SVG (una con spazio e accento nel nome),
audio `[sound:*.wav]`, TTS inline `[anki:tts]`, MathJax, flag e carte in tutte le code:
nuove, in apprendimento e riapprendimento, da ripassare oggi o in ritardo, future, sospese
e seppellite. Ferma l'API prima di lanciarlo; senza `--force` non tocca una collezione esistente,
e con `--force` sposta la vecchia (media e collegamento AnkiWeb compresi) in `data/backup-seed-*`.

## Configurazione

Tutto da variabili d'ambiente (o `.env`), vedi [`.env.example`](../.env.example).

| Variabile | Default | |
|---|---|---|
| `ANKI_API_TOKEN` | — | Token della PWA (min. 16 caratteri) |
| `ANKI_API_TOKEN_FILE` | — | In alternativa: file che contiene il token (Docker secret, es. `/run/secrets/anki_api_token`); vince sulla variabile |
| `ANKI_WEB_DIR` | vuoto (`/srv/web` nel container) | Build della PWA da servire sulla stessa origine; vuoto = solo API |
| `ANKI_STUDIO_VERSION` / `_REVISION` | `dev` / vuoto | Versione e commit, li imposta il Dockerfile; li riporta `/api/health` |
| `ANKI_DATA_DIR` | `./data` (`/data` nel container) | Collezione, media, backup, chiave di sync |
| `ANKI_SYNC_ENDPOINT` | vuoto = AnkiWeb | URL di un sync server self-hosted |
| `ANKI_AUTO_SYNC_MINUTES` | `10` | Sync automatica (0 = solo manuale) |
| `ANKI_SYNC_ON_STARTUP` | `true` | Sync all'avvio (in background) |
| `ANKI_SYNC_IO_TIMEOUT` | `60` | Secondi senza dati prima di dare la rete per persa |
| `ANKI_BUSY_TIMEOUT` | `20` | Quanto una richiesta aspetta la collezione occupata prima del 503 |
| `ANKI_LANG` | `it` | Lingua di Anki per intervalli ("4g") e messaggi |
| `ANKI_LOG_FORMAT` | `text` (`json` nel container) | Formato dei log |
| `ANKI_TOKEN_MAX_FAILURES` / `_WINDOW_S` | `20` / `600` | Token sbagliati per IP prima del blocco |
| `ANKI_LOGIN_MAX_FAILURES` / `_WINDOW_S` | `5` / `900` | Login AnkiWeb falliti prima del blocco |
| `ANKIWEB_USERNAME` / `ANKIWEB_PASSWORD` | — | Login automatico al primo avvio (poi si possono togliere) |

## Sync

### Primo collegamento

Dalla PWA (Impostazioni → AnkiWeb) oppure:

```bash
TOKEN=...   # quello del .env
curl -X POST localhost:8000/api/sync/login -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"username":"tu@mail.it","password":"..."}'
curl -X POST localhost:8000/api/sync -H "Authorization: Bearer $TOKEN"
```

- La password **non viene salvata**: resta solo la chiave di sessione in `data/sync_auth.json`
  (permessi 600), che ricorda anche il server di sync. Se cambi `ANKI_SYNC_ENDPOINT` la chiave
  non vale più (`endpoint_mismatch: true`) e serve un nuovo login; il file non viene cancellato.
- Alla prima sync il server ha una collezione vuota, quindi scarica tutto da AnkiWeb
  (`full_download`), media compresi. Se invece è AnkiWeb a essere vuoto, il server carica la sua
  (`full_upload`). In entrambi i casi un lato non ha niente da perdere.
- I media si sincronizzano in background nel motore di Anki: avanzamento in `GET /api/sync` → `media`.

### Quando parte

- All'avvio (in background: l'API risponde subito anche se AnkiWeb è lento), ogni
  `ANKI_AUTO_SYNC_MINUTES` minuti e allo spegnimento. La PWA la forza con `POST /api/sync`.
- **Una sola alla volta.** Un `POST /api/sync` durante un'altra sync aspetta che finisca e poi
  ne fa una sua (che di solito non trova niente da fare); la sync automatica invece salta il giro.
- La sync automatica e quella allo spegnimento fanno prima un controllo leggero (`sync_status`)
  che **non blocca la collezione**: se non c'è niente da fare lo studio non si accorge di niente.
  Il pulsante "Sincronizza" fa sempre la sync completa del protocollo, come Anki desktop
  (il controllo leggero usa una cache di AnkiWeb di qualche minuto).
- Errori di rete o del server: la sync automatica riprova con backoff (30 s, 1, 2, 4, 8 min… fino
  all'intervallo normale, con un po' di jitter). Conflitto o logout: niente retry, serve l'utente.
- Durante una sync normale il motore blocca la collezione per qualche secondo; durante una sync
  completa anche per minuti. Le rotte che non la ottengono entro `ANKI_BUSY_TIMEOUT` rispondono
  **503** `"Sync in corso: riprova tra poco"` con `Retry-After`, invece di restare appese.
- Allo spegnimento: si aspetta la sync in corso (fino a 30 s), poi un'ultima sync con timeout
  breve, poi la collezione viene chiusa. Il container deve avere almeno 120 s prima del SIGKILL
  (`stop_grace_period: 120s` nei file compose, `docker stop -t 120`): il default di Docker è 10 s.

### Stato (`GET /api/sync`)

Risponde subito anche durante una sync. Oltre a `logged_in`, `username`, `last_result` e `media`:

- `running`: `"normal"`, `"full_upload"`, `"full_download"` o `null`; `running_since`.
- `progress`: per la sync completa `{kind: "full_sync", transferred, total}` (byte), per quella
  normale `{kind: "normal_sync", stage, added, removed}` (testi già tradotti).
- `full_sync_required`: l'ultima sync ha trovato un conflitto (vedi sotto).
- `endpoint` (`null` = AnkiWeb), `endpoint_mismatch`, `next_auto_sync_at`, `auto_sync_failures`.
- `last_result.error_kind`: `network` (offline, si riprova da sola), `auth` (chiave revocata:
  rifai il login), `server` (AnkiWeb ha rifiutato, mostra `error`), `refused` (bloccata per non
  perdere dati), `other`.

`outcome` vale `synced` quando è stata fatta una sync normale e `no_changes` quando non c'era
niente da scambiare. Nota: se due dispositivi sincronizzano a turno, Anki fa sempre una sync
normale (si scambiano il timestamp della collezione), quindi `synced` è normale.

### Conflitti: nessun dato perso senza una scelta

Se server e AnkiWeb sono divergenti in modo inconciliabile (es. hai cambiato un tipo di nota su
desktop), `POST /api/sync` risponde **409** e `full_sync_required` diventa `true`. Non succede
niente finché l'utente non sceglie, e la PWA chiama `POST /api/sync/full`:

- `{"direction":"download"}`: vince AnkiWeb. **Prima** il backend salva un backup della
  collezione del server in `data/backups/` (se il backup fallisce il download non parte).
- `{"direction":"upload"}`: vince il server, sovrascrive AnkiWeb. Rifiutato (409,
  `error_kind: "refused"`) se la collezione del server è vuota: quasi sempre è un errore.

Una chiave revocata (password AnkiWeb cambiata) fa dimenticare solo la chiave: la collezione resta
com'è e dopo un nuovo login si sincronizza normalmente.

## Backup e ripristino

Tutto lo stato vive in `/data` nel container: il volume `anki-studio_anki-data` con il
`docker-compose.yml` del repo, `./anki-studio/data` nello stack (sotto Backrest, vedi
[`deploy/stack/README.md`](../deploy/stack/README.md)):

```
/data/collection.anki2        la collezione (SQLite in modalità WAL)
/data/collection.media/       i file dei media
/data/collection.media.db2    l'indice dei media per la sync
/data/backups/*.colpkg        backup automatici (senza media)
/data/sync_auth.json          la chiave di sync (segreta)
```

**Backup automatici.** Il backend crea un `.colpkg` all'avvio e dopo ogni sync automatica, con la
rotazione di Anki (al massimo uno ogni 30 minuti; ne tiene un certo numero giornalieri, settimanali
e mensili), e sempre prima di un download completo. Non includono i media, che sono comunque su
AnkiWeb.

**Backup del volume** (a container fermo, così SQLite è coerente):

```bash
docker compose stop anki-studio
docker run --rm -v anki-studio_anki-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/anki-data-$(date +%F).tgz -C /data .
docker compose start anki-studio
```

**Ripristino del volume:**

```bash
docker compose stop anki-studio
docker run --rm -v anki-studio_anki-data:/data -v "$PWD":/backup alpine \
  sh -c 'rm -rf /data/* && tar xzf /backup/anki-data-AAAA-MM-GG.tgz -C /data && chown -R 1000:1000 /data'
docker compose start anki-studio
```

Ripristina sempre **insieme** `collection.media/` e `collection.media.db2`: se l'indice dice che
un file c'era e la cartella non ce l'ha, la sync dei media lo considera cancellato e lo cancella
anche da AnkiWeb (è il comportamento di Anki).

**Ripristino di un solo `.colpkg`** (es. dopo un download completo sbagliato): copialo fuori
(`docker compose cp anki-studio:/data/backups/backup-….colpkg .`) e importalo in Anki desktop
(File → Importa, sostituisce la collezione), poi sincronizza da desktop scegliendo "Carica su
AnkiWeb"; infine sul server `POST /api/sync/full {"direction":"download"}`.

Dopo un ripristino del volume il server può essere "indietro" rispetto ad AnkiWeb: la prima sync
fonde le modifiche o, se servisse, chiede di scegliere (409) senza toccare niente.

## Sicurezza

- **Token**: tutte le rotte `/api/*` (tranne `/api/health`) richiedono
  `Authorization: Bearer <ANKI_API_TOKEN>`. Dopo `ANKI_TOKEN_MAX_FAILURES` token sbagliati nella
  finestra, quell'IP riceve **429** con `Retry-After` per tutte le richieste, anche con il token
  giusto (altrimenti chi indovina se ne accorgerebbe). Contano solo i tentativi veri: un `<img>`
  senza cookie non incrementa il contatore.
- **Login AnkiWeb**: al massimo `ANKI_LOGIN_MAX_FAILURES` falliti nella finestra, per IP e in totale.
- **Cookie dei media** (`POST /api/auth/session`): `anki_media`, `HttpOnly`, `Secure`,
  `SameSite=Strict`, `Path=/api/media`. Non contiene il token (è un HMAC derivato) e apre
  solo `GET /api/media/*`. Su `http://localhost` in sviluppo non è `Secure`.
- **Header**: su `/api/*` `X-Content-Type-Options`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`, `Cross-Origin-Resource-Policy`, `Cache-Control: no-store` (i media
  hanno la loro cache), una CSP restrittiva e, sui media, `sandbox`: un `.svg` o `.html` della
  collezione aperto direttamente non esegue script sulla nostra origine. `Strict-Transport-Security`
  se la richiesta arriva in HTTPS.
- **Log senza segreti**: token, chiave di sync e password usate per il login vengono oscurati
  (`***`) in ogni messaggio e traceback; il log di accesso registra solo metodo, path, stato e
  durata, mai query string o header.
- **Dietro proxy**: uvicorn gira con `--proxy-headers` e `FORWARDED_ALLOW_IPS` limitato alle reti
  private (vedi `Dockerfile`), quindi `X-Forwarded-For`/`-Proto` contano solo se arrivano da
  Traefik (o da un altro proxy sulla rete privata). Il proxy pubblico (Traefik) deve **sovrascrivere** l'`X-Forwarded-For` dei client
  (è il default di Traefik: non attivare `forwardedHeaders.insecure` né mettere IP pubblici in
  `trustedIPs` sull'entrypoint), altrimenti un client potrebbe fingersi un altro IP e aggirare il
  rate limit. Nello stack il container non pubblica porte: ci arriva solo Traefik, sulla sua
  rete edge dedicata.
- **Body**: al massimo 50 MB per richiesta (413 oltre), anche prima del controllo del token
  (era `client_max_body_size` di nginx).
- **PWA**: sui file statici `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  `Cross-Origin-Resource-Policy` e, su `index.html`, una CSP che ammette solo gli script dell'app
  (`script-src 'self'` più l'hash dello script inline di `index.html`, calcolato all'avvio).
  Immagini, font e stili restano liberi: le carte della collezione possono usarli.
- **Configurazione**: un errore di validazione delle variabili non stampa mai i valori
  (token e password AnkiWeb non finiscono nei log del container).

## Healthcheck e log

`GET /api/health` (senza token) risponde
`{"ok": true, "collection": "open" | "busy", "syncing": …, "version": "0.1.0", "revision": "<commit>"}`:
verifica che la collezione risponda a una query. Durante una sync lunga vale `busy` ma resta 200,
perché un riavvio del container a metà sync sarebbe la cosa peggiore. 503 se la collezione è chiusa
o illeggibile.

L'immagine ha lo stesso controllo come `HEALTHCHECK`.

Con `ANKI_LOG_FORMAT=json` ogni evento è una riga JSON (`ts`, `level`, `logger`, `msg` e campi
come `method`, `path`, `status`, `ms`, `client`, `outcome`, `error_kind`).

## HTTPS per l'iPad

Una PWA installata su iPad richiede HTTPS. In produzione lo fornisce il Traefik dello stack; per i test:

- **Tailscale** (consigliato, nessuna porta aperta su internet):
  `tailscale serve --bg 8080` (porta pubblicata dal `docker-compose.yml` del repo) →
  `https://<macchina>.<tailnet>.ts.net`

La PWA e l'API stanno **sulla stessa origine**: lo stesso processo serve i file statici
(`app/web.py`) e `/api`. Così non serve CORS e il cookie per i media funziona senza problemi. Solo se servi la PWA da un'altra origine va aggiunta in
`ANKI_CORS_ORIGINS`.

## API

| Metodo | Rotta | Cosa fa |
|---|---|---|
| GET | `/api/health` | Stato della collezione (senza token) |
| GET | `/api/decks` | Albero dei mazzi con conteggi nuove/in apprendimento/da ripassare |
| GET | `/api/stats/today` | Review di oggi, tempo, "Di nuovo" |
| GET | `/api/stats?deck_id=&days=30` | Carte per stato, review per giorno, ritenzione, previsione a 7 giorni |
| GET | `/api/decks/{id}/study` | Prossima carta del mazzo (`done: true` se hai finito) |
| POST | `/api/decks/{id}/study/answer` | `{card_id, rating: 1-4, time_taken_ms}`, restituisce già la carta successiva |
| POST | `/api/decks/{id}/study/undo` | Annulla l'ultima azione (409 se non c'è niente) |
| GET | `/api/decks/{id}/options` | Preset del mazzo (limiti, passi, FSRS), sola lettura |
| POST | `/api/decks/{id}/extend-limits` | `{new, review}`: "studia altre N carte oggi", restituisce lo StudyState |
| POST | `/api/cards/{id}/bury` · `/suspend` | Seppellisci / sospendi (204; con `?deck_id=` → StudyState) |
| POST | `/api/cards/{id}/flag` | `{flag: 0-7}` |
| POST | `/api/cards/{id}/type-answer` | `{typed}` → `{answer_html}` con il confronto di Anki |
| GET | `/api/notetypes` | Tipi di nota con i loro campi |
| POST | `/api/notes` | Crea nota `{deck_id, notetype_id, fields: {Front: …}, tags}` |
| GET/PATCH | `/api/notes/{id}` | Leggi / modifica campi e tag |
| GET | `/api/search/notes?q=&limit=&offset=` | Ricerca con la sintassi di Anki (400 se non valida) |
| GET | `/api/tags` | Tutti i tag |
| GET | `/api/media/{file}` | Immagini e audio delle carte (Bearer o cookie) |
| POST/DELETE | `/api/auth/session` | Imposta / toglie il cookie per i media |
| GET | `/api/sync` | Stato della sync (vedi sopra) |
| POST | `/api/sync/login` · `/logout` | Collega o scollega AnkiWeb (429 dopo troppi tentativi) |
| POST | `/api/sync` | Sync normale (409 = serve la sync completa) |
| POST | `/api/sync/full` | `{direction: "upload" \| "download"}`, solo dopo conferma dell'utente |

Codici comuni: **401** token mancante o sbagliato, **429** troppi tentativi (`Retry-After`),
**503** collezione occupata da una sync (`Retry-After`), **502** AnkiWeb non raggiungibile.

### Note per la PWA

- **Carta**: `question_html` / `answer_html` vanno inseriti dentro
  `<div class="{card_class}">`, con lo `css` del tipo di nota in uno `<style>` (gli `url()`
  relativi del CSS sono già riscritti in `/api/media/…`). Meglio uno Shadow DOM o un iframe,
  così il CSS della carta non tocca il resto dell'app.
- **Media**: gli `src` sono già riscritti in `/api/media/...`. I tag `<img>` non
  possono inviare header, quindi all'avvio la PWA chiama una volta `POST /api/auth/session`
  e da lì il browser invia il cookie da solo.
- **Audio**: i `[sound:…]` diventano `<button class="anki-play" data-side="q|a" data-index="N">`.
  `question_av[N]` / `answer_av[N]` contengono l'URL del file oppure il testo da leggere con TTS
  (`speechSynthesis`). `autoplay` indica se riprodurli subito.
- **Pulsanti**: `button_labels` contiene gli intervalli dei 4 pulsanti in italiano, es.
  `["<1min","<6min","<10min","4g"]`.
- **Risposta digitata**: le carte con `{{type:Campo}}` hanno `[[type:Campo]]` nell'HTML; la PWA
  mostra un campo di testo e, girando la carta, chiede `POST /api/cards/{id}/type-answer`.
- **Annulla**: `StudyState.undo_label` dice cosa annullerebbe (es. "Rispondi alla carta"), `null`
  se niente. Dopo un cambio di mazzo è `null`: non si annulla una risposta data in un altro mazzo.
- **Tempo**: misura sul client quanto ci metti a rispondere e invialo in `time_taken_ms`.
  Il server lo limita al massimo impostato nel preset del mazzo, come fa Anki desktop.
- Un **409** su `answer` significa che la coda è cambiata, per esempio dopo una sync: basta ricaricare `GET /study`.

## Dipendenze

`requirements.lock` fissa versioni e hash di tutte le dipendenze per l'immagine (e per la CI).
Dopo un cambio in `pyproject.toml`:

```bash
uv pip compile pyproject.toml --universal --generate-hashes --python-version 3.13 -o requirements.lock
```

## Test

```bash
.venv/bin/python -m pytest -q
```

`tests/test_web.py` copre il serving della PWA: cache, fallback SPA, confine con `/api`, header,
limite al body, token da file e versione in `/api/health`.

`tests/test_sync_e2e.py` avvia per ogni test un sync server locale (`python -m anki.syncserver`,
lo stesso protocollo di AnkiWeb) e un secondo client che fa da "Anki desktop": login, primo full
upload/download con i media, sync normale con review da entrambi i lati, conflitto 409 →
`/sync/full` in entrambe le direzioni (con backup), media nei due sensi, cambio di endpoint e
redirect del server, chiave revocata, rete giù, una sync alla volta con 503 e stato "in corso",
sync all'avvio e allo spegnimento. Nessun test parla con il vero AnkiWeb.

### Provare con un sync server a mano

```bash
SYNC_USER1=io:segreta SYNC_BASE=/tmp/anki-sync SYNC_PORT=27701 .venv/bin/python -m anki.syncserver &
ANKI_API_TOKEN=un-token-lungo-almeno-16 ANKI_DATA_DIR=/tmp/anki-dev \
ANKI_SYNC_ENDPOINT=http://127.0.0.1:27701/ ANKIWEB_USERNAME=io ANKIWEB_PASSWORD=segreta \
  .venv/bin/uvicorn app.main:create_app --factory --port 8001
```

Anki desktop può puntare allo stesso server (Preferenze → Sync → server personalizzato) per
provare il giro completo con un client vero.
