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
ANKI_DEV_LOGIN=true ANKI_API_TOKEN=un-token-lungo-almeno-16 ANKI_DATA_DIR=./data \
  .venv/bin/uvicorn app.main:create_app --factory --reload --port 8000
```

`ANKI_DEV_LOGIN` sostituisce Authentik in sviluppo: la PWA (con `pnpm dev`) entra subito come
"Sviluppo". Il token serve solo per `curl`. Per provare il login vero in locale, configura le
variabili `ANKI_OIDC_*` (sotto) con una redirect URI `http://localhost:5173/api/auth/callback`.

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
| `ANKI_PUBLIC_URL` | — | URL pubblico dell'app (es. `https://anki.jshep.xyz`): redirect URI `<url>/api/auth/callback` e origine attesa |
| `ANKI_OIDC_ISSUER` | — | Issuer del provider Authentik, es. `https://auth.jshep.xyz/application/o/anki-studio/` |
| `ANKI_OIDC_CLIENT_ID` | — | Client ID del provider (client confidenziale) |
| `ANKI_OIDC_CLIENT_SECRET` / `_FILE` | — | Client secret, o il file che lo contiene (Docker secret); il file vince |
| `ANKI_OIDC_SCOPES` | `openid profile email` | Scope richiesti |
| `ANKI_OIDC_ALLOWED_USERS` / `_GROUPS` | vuoti | Seconda barriera dopo le policy di Authentik: `preferred_username`/email o gruppi ammessi (virgole). Vuoti = decide Authentik |
| `ANKI_SESSION_DAYS` | `30` | Durata della sessione della PWA; scaduta, la PWA rifà il login da sola |
| `ANKI_DEV_LOGIN` | `false` | Solo sviluppo: login senza Authentik. Rifiutato insieme ad `ANKI_WEB_DIR` |
| `ANKI_MCP_ENABLED` | `true` | Server MCP su `/mcp` (e metadati OAuth). `false` = niente `/mcp` né `.well-known` (404) |
| `ANKI_MCP_OIDC_ISSUER` | — | Issuer del SECONDO provider Authentik, quello per l'app Claude, es. `https://auth.jshep.xyz/application/o/anki-studio-mcp/` (solo `https`). Vuoto = niente OAuth su `/mcp`, restano i token Bearer |
| `ANKI_MCP_OIDC_CLIENT_ID` | — | Client ID di quel provider: è il valore atteso nell'`aud` dei JWT (non l'URL della risorsa). Il backend **non** ha il client secret: lo usa Claude |
| `ANKI_MCP_OAUTH_REVIEW` | `true` | Le note create da Claude via OAuth nascono bozze da approvare nella PWA |
| `ANKI_API_TOKEN` / `_FILE` | — | Facoltativo, per script e test: `Authorization: Bearer` (min. 16 caratteri). È il token "amministratore": può tutto. La PWA non lo usa. I token per gli agenti si creano dalla PWA o da `/api/tokens` (vedi "Agenti, bozze e token") |
| `ANKI_WEB_DIR` | vuoto (`/srv/web` nel container) | Build della PWA da servire sulla stessa origine; vuoto = solo API |
| `ANKI_STUDIO_VERSION` / `_REVISION` | `dev` / vuoto | Versione e commit, li imposta il Dockerfile; li riporta `/api/health` |
| `ANKI_DATA_DIR` | `./data` (`/data` nel container) | Collezione, media, backup, chiave di sync |
| `ANKI_SYNC_ENDPOINT` | vuoto = AnkiWeb | URL di un sync server self-hosted |
| `ANKI_AUTO_SYNC_MINUTES` | `10` | Sync automatica (0 = solo manuale) |
| `ANKI_SYNC_ON_STARTUP` | `true` | Sync all'avvio (in background) |
| `ANKI_SYNC_AFTER_WRITE_SECONDS` | `30` | Dopo una scrittura da agente (o dalle rotte hub) la sync parte da sola dopo questi secondi, con più scritture raggruppate in una; `0` = spenta. Niente da fare se AnkiWeb non è collegato |
| `ANKI_SYNC_IO_TIMEOUT` | `60` | Secondi senza dati prima di dare la rete per persa |
| `ANKI_BUSY_TIMEOUT` | `20` | Quanto una richiesta aspetta la collezione occupata prima del 503 |
| `ANKI_LANG` | `it` | Lingua di Anki per intervalli ("4g") e messaggi |
| `ANKI_LOG_FORMAT` | `text` (`json` nel container) | Formato dei log |
| `ANKI_TOKEN_MAX_FAILURES` / `_WINDOW_S` | `20` / `600` | Bearer sbagliati (e, a parte, login OIDC falliti) per IP prima del blocco; vedi "Sicurezza" |
| `ANKI_LOGIN_MAX_FAILURES` / `_WINDOW_S` | `5` / `900` | Login AnkiWeb falliti prima del blocco |
| `ANKIWEB_USERNAME` / `ANKIWEB_PASSWORD` | — | Login automatico al primo avvio (poi si possono togliere) |

## Sync

### Primo collegamento

Dalla PWA (Impostazioni → AnkiWeb) oppure, se hai impostato `ANKI_API_TOKEN`:

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

- **Accesso con Authentik (OIDC)**: tutte le rotte `/api/*` (tranne `/api/health` e
  `/api/auth/login|callback|logout`) richiedono la sessione. Il backend è un client OIDC
  *confidenziale* (Authorization Code + PKCE, `state`, `nonce`): fa lui lo scambio del codice e la
  PWA non vede mai codici né token, solo il cookie. Dell'ID token controlla `iss`, `aud`, `azp`,
  `exp`, `iat` e `nonce`; la firma no, perché arriva direttamente dal token endpoint su TLS (OIDC
  Core §3.1.3.7, punto 6), e per questo l'issuer deve essere `https://`. Chi può entrare lo
  decidono le policy dell'applicazione su Authentik, più `ANKI_OIDC_ALLOWED_USERS`/`_GROUPS`.
- **Cookie di sessione** `anki_studio_session`: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`,
  firmato (HMAC-SHA256, chiave derivata dal client secret: sopravvive ai riavvii, e cambiare il
  secret su Authentik chiude tutte le sessioni), dura `ANKI_SESSION_DAYS`. Contiene solo `sub`,
  nome e scadenza. Vale anche per `<img>`/`<audio>` delle carte. Su `http://localhost` non è `Secure`.
  Il login in corso (`state`, `nonce`, verifier PKCE) sta 10 minuti in `anki_studio_login`
  (`Path=/api/auth`), usa e getta.
- **CSRF**: le richieste che modificano dati con il cookie devono arrivare dalla stessa origine
  (`Sec-Fetch-Site: same-origin`, o `Origin` uguale a `ANKI_PUBLIC_URL`), altrimenti **403**.
  `SameSite=Lax` da solo non basta: gli altri sottodomini di `jshep.xyz` sono lo stesso "sito".
- **Token per gli script** (facoltativo): con `ANKI_API_TOKEN` impostato vale anche
  `Authorization: Bearer <token>`. Dopo `ANKI_TOKEN_MAX_FAILURES` Bearer sbagliati nella finestra,
  quell'IP riceve **429** con `Retry-After` per le richieste **che presentano un Bearer** (REST e
  `/mcp`), anche con la credenziale giusta (altrimenti chi indovina se ne accorgerebbe). Tre
  dettagli che evitano di chiudere fuori il proprietario:
  - il blocco riguarda solo chi manda un `Authorization: Bearer`: la PWA con il cookie di sessione
    (nessun Bearer) non indovina niente e non si ferma mai;
  - un Bearer che corrisponde a un token **revocato** risponde 401 ma **non conta** come tentativo:
    è l'agente di prima che ritenta (in `tokens.json` restano solo gli hash dei revocati, mai il
    chiaro, al massimo 500). Un token che non è mai esistito conta, quindi indovinare non diventa più
    facile;
  - i login OIDC con `state`/codice non validi hanno un contatore a parte (stessa soglia) che ferma
    solo `/api/auth/callback`.
- **`/mcp`** (server MCP): non usa cookie e il cookie di sessione **non** vale come credenziale (niente CSRF,
  niente autorità implicita); i token nella query string si ignorano. Vedi "Server MCP" qui sotto.
- **Login AnkiWeb**: al massimo `ANKI_LOGIN_MAX_FAILURES` falliti nella finestra, per IP e in totale.
- **Header**: su `/api/*`, `/mcp` e `/.well-known/*` `X-Content-Type-Options`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`, `Cross-Origin-Resource-Policy`, `Cache-Control: no-store` (i media
  hanno la loro cache), una CSP restrittiva e, sui media, `sandbox`: un `.svg` o `.html` della
  collezione (per esempio arrivato con la sync) aperto direttamente non esegue script sulla nostra origine. `Strict-Transport-Security`
  se la richiesta arriva in HTTPS.
- **Log senza segreti**: token, client secret OIDC, chiave di sync e password usate per il login vengono oscurati
  (`***`) in ogni messaggio e traceback; il log di accesso registra solo metodo, path, stato e
  durata, mai query string o header.
- **Dietro proxy**: uvicorn gira con `--proxy-headers` e `FORWARDED_ALLOW_IPS` limitato alle reti
  private (vedi `Dockerfile`), quindi `X-Forwarded-For`/`-Proto` contano solo se arrivano da
  Traefik (o da un altro proxy sulla rete privata). Il proxy pubblico (Traefik) deve **sovrascrivere** l'`X-Forwarded-For` dei client
  (è il default di Traefik: non attivare `forwardedHeaders.insecure` né mettere IP pubblici in
  `trustedIPs` sull'entrypoint), altrimenti un client potrebbe fingersi un altro IP e aggirare il
  rate limit. Nello stack il container non pubblica porte: ci arriva solo Traefik, sulla sua
  rete edge dedicata.
- **Body**: al massimo 50 MB per richiesta (413 oltre), anche prima del controllo della sessione
  (era `client_max_body_size` di nginx). Su `/mcp` il tetto del trasporto è 15 MB (serve a `add_media`).
- **PWA**: sui file statici `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  `Cross-Origin-Resource-Policy` e, su `index.html`, una CSP che ammette solo gli script dell'app
  (`script-src 'self'` più l'hash dello script inline di `index.html`, calcolato all'avvio).
  Immagini, font e stili restano liberi: le carte della collezione possono usarli.
- **Configurazione**: un errore di validazione delle variabili non stampa mai i valori
  (token e password AnkiWeb non finiscono nei log del container).

## Healthcheck e log

`GET /api/health` (senza sessione) risponde
`{"ok": true, "collection": "open" | "busy", "syncing": …, "version": "26.0.1", "revision": "<commit>"}`:
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
(`app/web.py`) e `/api`. Così non serve CORS e il cookie di sessione funziona senza problemi. Solo se servi la PWA da un'altra origine va aggiunta in
`ANKI_CORS_ORIGINS`.

## API

| Metodo | Rotta | Cosa fa |
|---|---|---|
| GET | `/api/health` | Stato della collezione (senza sessione) |
| GET | `/api/auth/login?next=/…` | Navigazione: porta su Authentik e poi torna a `next` (solo percorsi della PWA) |
| GET | `/api/auth/callback` | Ritorno da Authentik: apre la sessione. Errori → `/?auth_error=denied\|forbidden\|expired\|unreachable\|blocked\|failed\|unconfigured` |
| GET | `/api/auth/me` | `{name, username}` dell'utente collegato, 401 senza sessione |
| POST | `/api/auth/logout` | Chiude la sessione → `{logout_url}` (end-session di Authentik) |
| GET | `/api/decks` | Albero dei mazzi con conteggi nuove/in apprendimento/da ripassare |
| GET | `/api/stats/today` | Review di oggi, tempo, "Di nuovo" |
| GET | `/api/stats?deck_id=&days=30` | Carte per stato, review per giorno, ritenzione, previsione a 7 giorni |
| GET | `/api/decks/{id}/study` | Prossima carta del mazzo (`done: true` se hai finito) |
| POST | `/api/decks/{id}/study/answer` | `{card_id, rating: 1-4, time_taken_ms}`, restituisce già la carta successiva |
| POST | `/api/decks/{id}/study/undo` | Annulla l'ultima risposta o azione **dello studio** (409 se non c'è niente: mai le modifiche di agenti, approvazioni o selezioni di mazzo) |
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
| GET | `/api/media/{file}` | Immagini e audio delle carte (con il cookie di sessione) |
| POST | `/api/media` | `{filename, data_base64}` → `{filename}` (201): carica un'immagine (png, jpg, gif, webp), un audio o un mp4/webm nei media (max 10 MB decodificati, 413 oltre). **Gli SVG non sono ammessi** (422: possono contenere codice e un filtro non basta, usa PNG/JPG/WebP). Estensione e contenuto devono coincidere, il nome si sanifica e Anki può cambiarlo: usa quello restituito nei campi. Token `write` e sessione |
| GET | `/api/sync` | Stato della sync (vedi sopra) |
| POST | `/api/sync/login` · `/logout` | Collega o scollega AnkiWeb (429 dopo troppi tentativi) |
| POST | `/api/sync` | Sync normale (409 = serve la sync completa) |
| POST | `/api/sync/full` | `{direction: "upload" \| "download"}`, solo dopo conferma dell'utente |
| POST | `/api/hub/notes/batch` | Hub: fino a 100 note (`HubBatchIn` → `HubBatchOut`), `dry_run`, `create_missing_decks`, `draft`; ogni nota ha il suo esito |
| POST | `/api/hub/decks` | `{name}` → crea il mazzo, idempotente (`created: false` se esisteva) |
| GET | `/api/hub/summary` · `/api/hub/drafts?limit&offset` | Numero di bozze (badge) · elenco delle bozze (ognuna con `modified`; `limit` al massimo **200**, default 50) |
| POST | `/api/hub/drafts/approve` · `/discard` | `{note_ids, expected_mod?}`: approva (carte riattivate) · scarta (cancella, solo bozze vere); → `{approved\|discarded, skipped_ids}` |
| GET | `/api/cards/{id}/preview` | La carta renderizzata fuori dalla coda (`CardPreview`), anche se sospesa |
| POST | `/api/notes/{id}/move` | `{deck_id}`: sposta tutte le carte della nota |
| DELETE | `/api/notes/{id}` | Cancella la nota con le sue carte (204) |
| POST | `/api/notes/tags` | `{note_ids, add, remove}`: tag in blocco → `{updated}`; 422 se toccano `hub::`, `agent::`, `ext::` |
| GET/POST/PATCH/DELETE | `/api/tokens[/{id}]` | Token per gli agenti: elenco · crea (token in chiaro **solo qui**) · `scope`/`review` · revoca |
| WS | `/api/remote?role=screen&screen_id=…` · `?role=remote` | Telecomando: lo studio aperto (`screen`) e il telefono (`remote`), vedi sotto |

Codici comuni: **401** sessione mancante o scaduta (la PWA rifà il login), **403** modifica da un'altra origine, **429** troppi tentativi (`Retry-After`),
**503** collezione occupata da una sync (`Retry-After`), **502** AnkiWeb non raggiungibile.

### Note per la PWA

- **Carta**: `question_html` / `answer_html` vanno inseriti dentro
  `<div class="{card_class}">`, con lo `css` del tipo di nota in uno `<style>` (gli `url()`
  relativi del CSS sono già riscritti in `/api/media/…`). Meglio uno Shadow DOM o un iframe,
  così il CSS della carta non tocca il resto dell'app.
- **Accesso**: all'avvio `GET /api/auth/me`; con 401 la PWA naviga (non `fetch`) su
  `/api/auth/login?next=<pagina corrente>`. Un 401 più avanti vuol dire sessione scaduta: stesso giro.
- **Media**: gli `src` sono già riscritti in `/api/media/...`; il browser manda da solo il cookie
  di sessione anche per `<img>` e `<audio>`.
- **Audio**: i `[sound:…]` diventano `<button class="anki-play" data-side="q|a" data-index="N">`.
  `question_av[N]` / `answer_av[N]` contengono l'URL del file oppure il testo da leggere con TTS
  (`speechSynthesis`). `autoplay` indica se riprodurli subito.
- **Pulsanti**: `button_labels` contiene gli intervalli dei 4 pulsanti in italiano, es.
  `["<1min","<6min","<10min","4g"]`.
- **Risposta digitata**: le carte con `{{type:Campo}}` hanno `[[type:Campo]]` nell'HTML; la PWA
  mostra un campo di testo e, girando la carta, chiede `POST /api/cards/{id}/type-answer`.
- **Annulla**: `StudyState.undo_label` dice cosa annullerebbe (es. "Rispondi alla carta"), `null`
  se niente. Dopo un cambio di mazzo è `null`: non si annulla una risposta data in un altro mazzo.
  È `null` anche se l'ultima operazione annullabile non è dello studio (un agente ha aggiornato una
  nota, si è approvata una bozza...): la pila di undo di Anki è una sola, ma lo studio tiene il conto
  delle *sue* operazioni (risposta, seppellisci, sospendi, flag) e non annulla mai quelle di altri.
- **Tempo**: misura sul client quanto ci metti a rispondere e invialo in `time_taken_ms`.
  Il server lo limita al massimo impostato nel preset del mazzo, come fa Anki desktop.
- Un **409** su `answer` significa che la coda è cambiata, per esempio dopo una sync: basta ricaricare `GET /study`.
- **Telecomando** (`app/remote.py`): WebSocket con il cookie di sessione e l'origine della PWA
  (un'altra origine viene rifiutata all'handshake). La PWA aperta (in ogni schermata tranne
  il telecomando stesso) si collega come `screen` e manda `{"type":"state","state":RemoteScreenState,"claim":bool}`; il telefono come
  `remote` riceve `{"type":"state","screen":…|null}` e manda `{"type":"command","command":RemoteCommand}`
  (`reveal`, `answer` con `rating`, `undo`, `replay`, `bury`, `suspend`, `flag` con `flag`,
  `open_deck` con `deck_id`, `close`). `view` dice cosa mostra lo schermo: `decks` (il telefono
  può aprire un mazzo), `study`, `other` (aggiungi, impostazioni: il telefono non la cambia). Il server inoltra soltanto, in memoria: lo
  studio vero resta nella schermata, che esegue il comando solo se `card_id` è ancora la carta
  mostrata. Con più schermate aperte comanda quella in primo piano per ultima (`claim`).
  Niente abbinamento: stesso account, stessa collezione.

## Agenti, bozze e token

Contratto e motivazioni in [`docs/PIANO-HUB.md`](../docs/PIANO-HUB.md); la logica sta in `app/hub.py`
(senza FastAPI, la usa anche il server MCP) e le rotte in `routers/hub.py`, `routers/notes.py`,
`routers/tokens.py`.

**Token.** `ask_` + 32 byte casuali. Sul disco (`data/tokens.json`, 0600, scrittura atomica) resta
solo l'hash SHA-256: il chiaro si vede una volta sola, nella risposta di `POST /api/tokens`, e non si
recupera. Ogni token ha `scope` (`read` | `write`), `review` (le sue note nascono bozza) e `last_used_at`.
Il nome diventa lo slug del tag di provenienza `agent::<slug>` (`a-z0-9-`), quindi è unico e non si
cambia. I Bearer sbagliati contano nel limite per IP di `ANKI_API_TOKEN` (429, solo per chi manda un Bearer: vedi "Sicurezza"); uno revocato risponde 401 senza contare. Se `tokens.json` non si legge (JSON rovinato, forma sbagliata) non viene sovrascritto: si rinomina in `tokens.json.bak-<data>` (0600), con un warning senza contenuti, e si riparte senza token; i campi sconosciuti nei token (file di una versione più nuova) si ignorano.

**Chi può cosa** (un solo controllo in `security.token_may`, deny-by-default: una rotta nuova è
vietata ai token con scope finché non la si elenca lì):

| | sessione e `ANKI_API_TOKEN` | token `write` | token `read` |
|---|---|---|---|
| `GET` decks, notetypes, search/notes, tags, notes/{id}, cards/{id}/preview, hub/summary, hub/drafts, sync | sì | sì | sì |
| `POST` hub/notes/batch, hub/decks, sync, media | sì | sì | 403 |
| `PATCH` notes/{id} | sì (ma non i tag riservati: 422) | **solo note col proprio tag `agent::<nome>`** (i tag riservati restano com'erano; con `review` una nota già approvata torna bozza) | 403 |
| approva/scarta bozze, move, `DELETE` note, tag in blocco, `/tokens`, sync login/logout/full, studio, statistiche, `GET` media, `auth/me`, telecomando | sì | 403 | 403 |

Un token con scope risponde 403 con "Questo token non può fare questa operazione".

**Creare note.** `POST /api/hub/notes/batch` (max 100 note, 422 oltre). Per ogni nota `deck` e
`notetype` si danno per nome o per id; l'esito è per nota e un errore non ferma le altre:
`created`, `updated`, `unchanged`, `duplicate` o `error` (campo inesistente, tipo di nota o mazzo
mancante senza `create_missing_decks`, primo campo vuoto, cloze mancante...). `dry_run` restituisce
lo stesso esito che avrebbe la scrittura senza scrivere niente (nemmeno i mazzi). Tutta la batch è
**una sola voce di undo** (`col.undo()`); lo studio non la propone come "Annulla".
Tetti: **200 KB per campo** e **2 MB per batch** (UTF-8, campi e tag): oltre, 422 con il motivo e
non si scrive niente (anche in `dry_run`); stessi tetti ai campi di `PATCH /notes/{id}` da token.

- **Idempotenza**: `external_id` (1-200 caratteri tra `A-Za-z0-9._:-`, altrimenti 422) → tag
  `ext::<id>`, cercato con il tag intero (niente jolly, niente figli `ext::x::y`). Rimandare la nota la
  aggiorna (campi passati, tag nuovi: quelli vecchi non si tolgono) o la lascia com'è (`unchanged`);
  il mazzo non cambia. Un token vede solo i propri `external_id`. Senza `external_id`, un primo campo uguale
  a una nota dello stesso tipo dà `duplicate` (con `note_id` di quella esistente); con `external_id`
  l'agente dice che è un'altra nota e si crea.
- **Provenienza**: le note di un token hanno `agent::<slug>`; quelle della sessione o di
  `ANKI_API_TOKEN` no. I tag `agent::`, `ext::` e `hub::` passati nella richiesta si ignorano, e gli spazi
  nei tag diventano `_`.
- **Bozze**: carte sospese + tag `hub::bozza`, quindi fuori dallo studio. Un token con `review` ha
  sempre bozze (`draft: false` non vale); gli altri scelgono con `draft` (default: note normali).
  `approve` toglie il tag e riattiva le carte; `discard` cancella **solo** bozze vere: con `hub::bozza`,
  carte tutte sospese e **mai ripassate** (`reps == 0`, `type == 0`, nessuna riga in `revlog`): il tag
  da solo non basta, può averlo messo chiunque da Anki desktop o da un altro dispositivo. Solo
  sessione/amministratore.
  - **Non si aggira l'approvazione.** Un token con `review` che modifica una nota già approvata
    (rimandando lo stesso `external_id`, `PATCH /notes/{id}`, `add_notes`/`update_note` di MCP) la
    RIMETTE in bozza (tag + carte sospese), purché la modifica cambi davvero qualcosa. Un token senza
    `review` non cambia lo stato. Dopo ogni modifica di una bozza (token, `PATCH` della sessione,
    Inbox) si sospendono **tutte** le sue carte non sospese: aggiungere `{{c2::…}}` genera una carta
    nuova che non deve entrare nello studio.
  - **Solo ciò che l'utente ha visto.** Ogni bozza ha `modified` (`note.mod`, secondi). La PWA lo
    rimanda in `expected_mod` (`{id: modified}`): se la nota è cambiata nel frattempo (un agente ha
    aggiornato la bozza) si SALTA e l'id va in `skipped_ids`, come quelli che non sono più bozze, non
    esistono o (per `discard`) non sono bozze vere. Senza `expected_mod` si tratta tutto quello che è
    una bozza. `mod` ha la risoluzione del secondo: una modifica nello stesso secondo in cui l'utente
    ha caricato l'elenco non si vede.
  - **Tag riservati** (`hub::…`, `agent::…`, `ext::…`, anche con maiuscole o spazi diversi): non si
    aggiungono né si tolgono a mano. `POST /notes/tags` e `PATCH /notes/{id}` della sessione rispondono
    **422** (la PWA nel `PATCH` rimanda quelli che la nota ha già e passa; per le bozze si usano
    approva e scarta). In `remove` si rifiutano anche i genitori `hub`, `agent`, `ext` (in Anki
    togliere `hub` toglie anche `hub::bozza`). I token con scope nel `PATCH` li ignorano, come alla creazione.
- **Anteprima**: `GET /api/cards/{id}/preview` rende la carta come lo studio (stessi media, CSS e
  `card_class`) ma senza coda: serve anche per le carte sospese.
- **Sync dopo la scrittura**: vedi `ANKI_SYNC_AFTER_WRITE_SECONDS`. Un timer a finestra fissa raggruppa le
  scritture ravvicinate in una sola sync, che aspetta il suo turno se un'altra è in corso (una alla
  volta) e non parte se AnkiWeb non è collegato o c'è un conflitto da risolvere.

```bash
ADMIN=...   # ANKI_API_TOKEN
TOKEN=$(curl -s -X POST localhost:8000/api/tokens -H "Authorization: Bearer $ADMIN" \
  -H 'Content-Type: application/json' -d '{"name":"Claude","scope":"write","review":true}' | jq -r .token)
curl -s -X POST localhost:8000/api/hub/notes/batch -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"dry_run":true,"create_missing_decks":true,"notes":[
    {"deck":"Lingue::Spagnolo","notetype":"Basic","fields":{"Front":"saltar","Back":"saltare"},"external_id":"v-saltar"}]}'
```

## Server MCP (`/mcp`)

Un server MCP **nello stesso processo** dell'API (streamable HTTP, `app/mcp_server.py`): la collezione
resta aperta una volta sola, sotto lo stesso `RLock`. Gli strumenti chiamano le funzioni delle rotte
REST (`app/hub.py` e `routers/*`): stesse regole, stesse bozze, stessi errori, e dopo ogni scrittura
parte `request_soon()` (sync con AnkiWeb dopo `ANKI_SYNC_AFTER_WRITE_SECONDS`). Piano e motivazioni in
[`docs/PIANO-HUB.md`](../docs/PIANO-HUB.md).

**Strumenti** (descrizioni in italiano, con `title` e annotazioni `readOnlyHint`/`destructiveHint`/`idempotentHint`):

| Strumento | Cosa fa | Serve |
|---|---|---|
| `list_decks` | Albero dei mazzi con id, nome completo e conteggi | `read` |
| `list_notetypes` | Tipi di nota con i nomi esatti dei campi | `read` |
| `search_notes` | Ricerca con la sintassi di Anki (`query`, `limit` ≤ 100, `offset`) | `read` |
| `get_note` | Una nota intera (campi, tag, mazzo, carte, `draft`) | `read` |
| `add_notes` | Fino a 100 note: `dry_run`, `create_missing_decks`, `draft`, `external_id` per nota; esito per nota | `write` |
| `update_note` | Campi e tag di una nota **creata dallo stesso accesso** (tag `agent::<nome>`) | `write` |
| `create_deck` | Crea un mazzo (idempotente) | `write` |
| `sync_now` | Sync normale con AnkiWeb | `write` |
| `sync_status` | Stato della sync | `read` |
| `add_media` | Immagine (png, jpg, gif, webp: **niente SVG**), audio o video breve in base64 (`filename`, `data_base64`, max 10 MB decodificati) | `write` |

**Non esistono** strumenti per cancellare, approvare o scartare bozze, sync completa o tipi di nota:
sono gesti dell'utente nella PWA. Il testo che arriva dalla collezione (`search_notes`, `get_note`) è
dato non fidato e le descrizioni lo dicono. Hanno `destructiveHint` solo `update_note` (sovrascrive i
campi che passi); `add_notes` no, anche se con lo stesso `external_id` aggiorna la *propria* nota
precedente.

**Permessi.** Ogni strumento corrisponde a una rotta REST e passa da `security.token_may` (una sola
matrice): un token `read` non scrive niente, `review` non si aggira (`draft: false` non vale),
`update_note` tocca solo le note col proprio `agent::<nome>` (con `review` una nota approvata torna bozza), i tag `agent::`, `ext::`, `hub::` sono
riservati. Un accesso senza identità (non passato da `/mcp`) è rifiutato. L'elenco degli strumenti è lo
stesso per tutti: uno strumento non permesso risponde con un errore che spiega cosa serve.

**Autenticazione** (`app/mcp_auth.py`), due modi:

1. **Bearer `ask_…`** (Hermes, Claude Code, script) e il vecchio `ANKI_API_TOKEN`: stessi token, scope e
   limite ai tentativi sbagliati (429) della REST.
2. **OAuth con Authentik** per l'app Claude, con un secondo provider (client confidenziale, redirect
   `https://claude.ai/api/mcp/auth_callback`, PKCE S256, `offline_access`, chiave di firma). Il backend
   riceve il JWT e ne **verifica la firma** con il JWKS dell'issuer (URL dal documento di discovery, in
   cache 1 h; un `kid` sconosciuto ricarica il JWKS una volta, al massimo una al minuto): solo `RS256` ed
   `ES256` (mai `none`, mai `HS*`), `iss`, `aud` (= `ANKI_MCP_OIDC_CLIENT_ID`), `exp`, `nbf`/`iat` con 60 s
   di tolleranza, `typ` se presente (`JWT`, `at+jwt`). L'utente è `preferred_username` (il `sub` di
   Authentik è opaco) o `email`; `ANKI_OIDC_ALLOWED_USERS/_GROUPS` si applicano come nel login della PWA.
   Se le liste sono impostate e nel JWT mancano `preferred_username`, `email` e `groups` la risposta è un
   **403** che lo dice (non si chiama lo userinfo endpoint: sarebbe una chiamata di rete in più sul
   percorso della richiesta; aggiungi gli scope `profile`/`email` al provider). Il risultato è un'identità
   `oauth`: scope `write`, `review` da `ANKI_MCP_OAUTH_REVIEW`, agente `claude` (tag `agent::claude`).
   I JWT non validi contano come tentativi sbagliati; se Authentik non è raggiungibile e non c'è cache la
   risposta è **503** con `Retry-After`, non un 401.

Risposte: senza credenziali **401** con `WWW-Authenticate: Bearer resource_metadata="<ANKI_PUBLIC_URL>/.well-known/oauth-protected-resource/mcp", scope="openid profile email offline_access"`
(più `error="invalid_token"` se il token c'era ma è sbagliato; senza OAuth configurato solo `Bearer`).
Mai redirect, né con né senza slash finale. `GET /.well-known/oauth-protected-resource[/mcp]` (pubblico,
**404** senza OAuth) restituisce `resource = <ANKI_PUBLIC_URL>/mcp` (esattamente l'URL da dare a Claude),
`authorization_servers = [ANKI_MCP_OIDC_ISSUER]`, `scopes_supported`, `bearer_methods_supported: ["header"]`.
`/mcp` e `/.well-known/*` non passano mai dal fallback della PWA (un 200 HTML farebbe ignorare a Claude il
challenge). La protezione DNS-rebinding dell'SDK ammette l'host di `ANKI_PUBLIC_URL` e `localhost`
(421 per gli altri; spenta se `ANKI_PUBLIC_URL` manca, in sviluppo: ogni richiesta ha comunque bisogno di un Bearer).

**Collegarlo.** Hermes / Claude Code / script: URL `https://…/mcp` e header `Authorization: Bearer ask_…`.
App Claude: connettore personalizzato con URL `<ANKI_PUBLIC_URL>/mcp` e, se serve, ID e secret del client
del provider Authentik (niente Dynamic Client Registration).

```bash
H=(-H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream')
curl -s localhost:8000/mcp "${H[@]}" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
curl -sN localhost:8000/mcp "${H[@]}" -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_decks","arguments":{}}}'
```

**Errori comuni**

| Cosa vedi | Perché |
|---|---|
| `401` + `invalid_token` | Token sbagliato, revocato, JWT scaduto, `aud`/`iss` diversi, firma non valida o `kid` che il provider non pubblica |
| `403` "Utente non ammesso" / "nel token mancano…" | `ANKI_OIDC_ALLOWED_USERS/_GROUPS` e claim del JWT (vedi sopra) |
| `429` | Troppi Bearer sbagliati da quell'IP (stesso limite della REST, solo per chi manda un Bearer; un token revocato non conta) |
| `503` Authentik non raggiungibile | Discovery o JWKS non scaricabili e nessuna cache |
| `421` / `403` Invalid Host / Origin | Host o `Origin` fuori da `ANKI_PUBLIC_URL`: controlla che Traefik non riscriva l'host |
| `413` | Body oltre 15 MB (50 MB per il resto del backend) |
| Errore dello strumento "occupata… riprova" | Collezione occupata (di solito una sync): equivale al 503 della REST |
| Errore dello strumento "scope «read»…" | L'accesso è `read`: serve `write` (Impostazioni → Agenti) |

**Note di implementazione.** SDK `mcp` **2.x** (`>=2.3,<3`): la linea stabile (Production/Stable dalla 2.0,
Python ≥ 3.10; il nostro Docker usa 3.13). `FastMCP` è `MCPServer` e il lifespan dell'app che la ospita
entra in `session_manager.run()` (lo fa `app/main.py`). Il server serve sia il protocollo 2025-11-25
(con `initialize`) sia il 2026-07-28 (senza handshake): lo decide l'SDK dall'header
`MCP-Protocol-Version`. È in modalità `stateless_http`: niente sessioni, quindi un riavvio dell'immagine
non lascia i client con un `Mcp-Session-Id` che dà 404, e l'identità si legge sempre dalla richiesta
corrente. Gli strumenti sono funzioni sincrone che l'SDK esegue in un thread.

## Dipendenze

`requirements.lock` fissa versioni e hash di tutte le dipendenze per l'immagine (e per la CI).
Dopo un cambio in `pyproject.toml`:

```bash
uv pip compile pyproject.toml --universal --generate-hashes --python-version 3.13 -o requirements.lock
```

Le dipendenze del server MCP sono `mcp>=2.3,<3` (tetto alla 3: un salto maggiore si prova prima) e
`PyJWT[crypto]` (firma dei JWT di Authentik); l'SDK porta con sé `httpx2`, `cryptography`, `jsonschema`
e `sse-starlette`.

## Test

```bash
.venv/bin/python -m pytest -q
```

`tests/test_web.py` copre il serving della PWA: cache, fallback SPA, confine con `/api`, header,
limite al body, token da file e versione in `/api/health`. `tests/test_auth.py` copre il login OIDC
con un provider finto: PKCE, `state`, controlli sull'ID token, utenti e gruppi ammessi, CSRF,
cookie manomessi, logout, login di sviluppo.

`tests/test_mcp.py` copre il server MCP (elenco e annotazioni degli strumenti, permessi per scope, bozze
e `review` non aggirabili, `update_note` solo sulle note proprie, errori chiari, collezione occupata, sync
dopo la scrittura, un client dell'SDK su un uvicorn vero con entrambe le versioni del protocollo e la
risposta in streaming); `tests/test_mcp_auth.py` l'accesso: 401 e metadati esatti, JWT con una coppia di
chiavi RSA/EC generata nei test e un JWKS finto (valido, scaduto, `iss`/`aud` sbagliati, firma sbagliata,
`alg=none`, HS256 firmato con la chiave pubblica, rotazione dei `kid`, claim e utenti ammessi), rate limit,
cookie che non valgono, Host ammessi, niente redirect; `tests/test_media.py` i media. Nessun test fa rete.

`tests/test_hub.py` copre batch, idempotenza, bozze, anteprima, spostamenti e tag; `test_hub_review.py` la revisione
(bozze rimesse in bozza, carte nuove sospese, `expected_mod`/`skipped_ids`, tag riservati, tetti); `test_tokens.py` i token
(hash a riposo, rate limit e blocco, revoca, file illeggibile); `test_permissions.py` la matrice dei permessi;
`test_route_matrix.py` classifica ogni rotta `/api/*` (una rotta nuova non elencata fa fallire il test);
`test_study_undo.py` l'«Annulla» dello studio; `test_busy.py` i 503 con la collezione occupata; `test_sync_after_write.py`
il debounce della sync dopo la scrittura.

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
