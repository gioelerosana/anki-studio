# Piano: Anki Studio come hub delle flashcard

Obiettivo: oltre a studiare, Anki Studio diventa il posto dove **arrivano le flashcard create
dagli agenti** (Claude, Hermes Agent, script) e dove le si rivede, le si cerca e le si
sistema. Poi viaggiano su AnkiWeb e da lì sugli altri dispositivi (la sync c'è già).

```
Claude (app) ──OAuth/Authentik──┐
Hermes Agent ──Bearer──────────┼─▶ /mcp (server MCP nello stesso processo) ─▶ hub.py ─▶ collezione ◀─sync─▶ AnkiWeb
script / curl ──Bearer─────────┘          REST /api/hub/*  ◀── PWA (Libreria, Attività, Token)
```

Lo scheduler, il rendering e la sync restano quelli di Anki (regole di AGENTS.md). Il server MCP
gira **nello stesso processo** della API: la collezione è aperta una sola volta (un solo worker,
un solo `RLock`), quindi niente servizio separato.

## Concetti

- **Provenienza.** Ogni nota creata da un token riceve il tag `agent::<nome>` (nome del token in
  minuscolo, solo `a-z0-9-`).
- **Idempotenza.** L'agente può passare un `external_id`: diventa il tag `ext::<id>`. Rimandare la
  stessa nota la aggiorna (o la lascia com'è) invece di duplicarla. Il tag viaggia con la sync.
- **Le note entrano subito.** Gli agenti scrivono direttamente nella collezione: note normali, con le
  carte attive, che la sync porta su AnkiWeb e sugli altri dispositivi. Non c'è nessuna quarantena da
  approvare (vedi «Bozze: scartate» più sotto).
- **Diario delle operazioni e annullamento.** È la rete di sicurezza: ogni operazione che modifica
  davvero la collezione (`add_notes`, `update_note`, `create_deck`) lascia una voce con lo stato di prima
  (`backend/app/journal.py`, `data/agent-ops.json`, ultime 200 e 30 giorni) e si annulla con
  `POST /api/hub/operations/{id}/undo` o dal tool MCP `undo_operation`: cancella le note create, rimette
  campi e tag delle aggiornate, elimina i mazzi creati se vuoti, e **salta** (dicendo perché) ciò che
  l'utente ha modificato o studiato nel frattempo.
- **Sync dopo la scrittura.** Dopo una scrittura da agente la sync parte da sola dopo
  `ANKI_SYNC_AFTER_WRITE_SECONDS` (default 30, `0` = spenta), con più scritture raggruppate in
  una sola sync. Se AnkiWeb non è collegato non fa niente.
- **Nessun dato perso (regola 1).** Gli agenti non cancellano, non fanno `/sync/full`, non toccano
  i tipi di nota. Cancellare è un gesto dell'utente nella PWA, con conferma.

## Contratto REST

I modelli sono in `backend/app/schemas.py` (sezione "hub") e in `apps/web/src/api/types.ts`;
i metodi della PWA in `apps/web/src/api/client.ts`. Le rotte vivono in `backend/app/routers/hub.py`
(più `notes.py` per le modifiche alle note) e usano un livello di servizio, `backend/app/hub.py`,
che usa anche il server MCP.

| Metodo | Rotta | Cosa fa | Chi |
|---|---|---|---|
| POST | `/api/hub/notes/batch` | `HubBatchIn` → `HubBatchOut`. Fino a 100 note, `dry_run`, `create_missing_decks`. Ogni nota ha il suo esito (un errore non ferma le altre). Una batch è **una sola operazione annullabile** (`operation_id`, null se non ha scritto niente). | token write, sessione |
| POST | `/api/hub/decks` | `HubDeckIn` → `HubDeckOut` (idempotente; `operation_id` se l'ha creato) | token write, sessione |
| GET | `/api/hub/operations?limit=50` | `{operations: OperationOut[]}`, dalla più recente (1..200). Un token vede solo le proprie | tutti |
| POST | `/api/hub/operations/{id}/undo` | `UndoOut` (`undone` \| `partial`, `restored`, `deleted`, `skipped`). 404 se non esiste (o è di un altro agente), 409 se già annullata | token write (solo le proprie), sessione |
| GET | `/api/cards/{id}/preview` | `CardPreview` (anche carte sospese) | tutti |
| POST | `/api/notes/{id}/move` | `NoteMoveIn` → `NoteOut` | **solo sessione** |
| DELETE | `/api/notes/{id}` | 204, cancella la nota con le sue carte | **solo sessione** |
| POST | `/api/notes/tags` | `NoteTagsIn` → `NoteTagsOut` | **solo sessione** |
| GET/POST/PATCH/DELETE | `/api/tokens[/{id}]` | `TokenOut` / `TokenIn` → `TokenCreated` / `TokenUpdate` / 204 | **solo sessione** |
| POST | `/api/media` | `MediaIn` → `MediaOut` (base64, max 10 MB, solo immagini/audio) | token write, sessione (fase 5) |

Rotte esistenti che restano: `GET /api/decks`, `/notetypes`, `/search/notes`, `/tags`, `/notes/{id}`,
`PATCH /notes/{id}` (la risposta porta `operation_id` se la modifica ha cambiato qualcosa), `/sync` (stato e `POST` per sincronizzare).

### Chi può cosa

Un'identità (`require_auth`) porta con sé `kind` (`session` | `admin` | `token` | `oauth`), `scope` e `name`.

- **Sessione della PWA** e il vecchio **`ANKI_API_TOKEN`** (compatibilità, è il token "amministratore"):
  tutto.
- **Token `read`**: solo le letture (`GET` su decks, notetypes, search/notes, tags, notes/{id},
  cards/{id}/preview, sync) e l'elenco delle **proprie** operazioni (`GET /hub/operations`); non annulla (403).
- **Token `write`**: le letture, più `POST /hub/notes/batch`, `POST /hub/decks`, `POST /sync`,
  `POST /media`, `PATCH /notes/{id}` **solo su note con il proprio tag `agent::<nome>`** e
  `POST /hub/operations/{id}/undo` **solo sulle proprie operazioni** (un id altrui è 404).
- Sessione e `ANKI_API_TOKEN` vedono e annullano le operazioni di tutti.
- Tutto il resto (cancellare, spostare, tag in blocco, token, login e sync completa, auth) risponde
  **403** a un token con scope.

I token sono `ask_` + 32 byte casuali, salvati come hash SHA-256 in `data/tokens.json` (0600,
scrittura atomica), mostrati in chiaro una volta sola, con limite ai tentativi sbagliati
(lo stesso `RateLimiter` di `ANKI_API_TOKEN`) e `last_used_at` aggiornato.

## Server MCP (`/mcp`)

Trasporto streamable HTTP, montato in `app/main.py` dal modulo `app/mcp_server.py`.
Strumenti (descrizioni in italiano, con `readOnlyHint`/`destructiveHint` corretti):

`list_decks`, `list_notetypes` (con i campi), `search_notes`, `get_note`, `add_notes` (batch,
`dry_run`), `update_note`, `create_deck`, `sync_now`, `sync_status`, `add_media`, più il diario:
`list_operations` (le proprie, `limit` default 20) e `undo_operation` (`operation_id`).
**Non esistono** strumenti per cancellare note, sync completa o tipi di nota: l'unica eccezione è
`undo_operation`, che agisce solo su ciò che l'agente stesso ha registrato. Le istruzioni del server
dicono che le note entrano subito (niente bozze) e che dopo un errore o un risultato sbagliato si
chiama `list_operations` e poi `undo_operation`; la descrizione di `undo_operation` avverte che salta le
note modificate dopo e che non annulla né i media né la sync. L'`operation_id` esce nell'esito di
`add_notes`, di `create_deck` (se crea) e di `update_note` (campo opzionale `operation_id` di `NoteOut`).
Il testo che arriva dalla collezione (`search_notes`, `get_note`) è dato non fidato: le
descrizioni degli strumenti lo dicono, e gli agenti con scope `write` non hanno comunque
niente di distruttivo a disposizione.

### Autenticazione di `/mcp`

1. **Bearer** `ask_…` (Hermes Agent, Claude Code, script): stessi token e stessi scope della REST.
2. **OAuth con Authentik** (app Claude: web, desktop, mobile): un **secondo provider** Authentik,
   confidenziale, con redirect `https://claude.ai/api/mcp/auth_callback`, PKCE S256, `offline_access`
   e una chiave di firma (JWT firmati, quindi con JWKS). Niente Dynamic Client Registration: la DCR
   di Authentik richiede già un token con uno scope dedicato e crea un provider per ogni
   registrazione, quindi Claude usa il client pre-registrato (ID e secret nel dialogo del
   connettore custom).
   - `/mcp` senza credenziali risponde `401` con `WWW-Authenticate: Bearer resource_metadata="…"`.
   - `/.well-known/oauth-protected-resource[/mcp]` dichiara `resource = <ANKI_PUBLIC_URL>/mcp` e
     `authorization_servers = [ANKI_MCP_OIDC_ISSUER]` (un solo elemento: Claude usa il primo).
   - Il backend **verifica la firma del JWT** (JWKS dell'issuer, in cache), più `iss`, `aud`
     (= `ANKI_MCP_OIDC_CLIENT_ID`), `exp` e gli utenti ammessi (`ANKI_OIDC_ALLOWED_USERS/_GROUPS`).
     Diversamente dal login della PWA, qui la firma conta: il token arriva da un client esterno.
   - Un utente autenticato via OAuth ha scope `write` e nome agente `claude`.
3. Mai token nella query string.

Variabili nuove: `ANKI_MCP_ENABLED` (default `true`), `ANKI_MCP_OIDC_ISSUER`,
`ANKI_MCP_OIDC_CLIENT_ID`, `ANKI_SYNC_AFTER_WRITE_SECONDS`.

Per l'app Claude `/mcp` e `auth.jshep.xyz` devono essere raggiungibili da internet (gli IP di
Anthropic sono `160.79.104.0/21`), senza WAF o filtri geografici in mezzo, e discovery, registrazione
e token endpoint hanno 10 secondi di tempo. Il deploy di prova su Tailscale basta per Hermes, non
per l'app Claude.

## PWA

- **Libreria** (`#/library`): ricerca con la sintassi di Anki, filtri rapidi per mazzo, tag e agente;
  anteprima della carta (`CardPreview`, in Shadow DOM come lo studio); modifica, sposta, tag in blocco,
  cancella con conferma.
- **Attività degli agenti**: le ultime operazioni (`GET /api/hub/operations`) con il loro riassunto e un
  tasto per annullarle (`POST …/undo`), che mostra cosa è stato saltato e perché.
- **Impostazioni → Agenti**: token (crea → mostra una volta e copia, `scope`, revoca, ultimo uso) e come
  collegare Claude e Hermes.

## Fasi

- [x] **1. Backend REST per gli agenti** — `app/hub.py`, `routers/hub.py`, token con scope,
      sync dopo la scrittura, test.
- [x] **2. PWA: Libreria, Attività, Agenti** — contro il contratto sopra.
- [x] **3. Deploy e Authentik** (proposta pronta in `deploy/stack/`, da applicare a mano) — blueprint del secondo provider, Traefik per `/mcp` e
      `.well-known`, variabili, guide di collegamento per Claude e Hermes.
- [x] **4. Server MCP + OAuth** — `app/mcp_server.py`, `app/mcp_auth.py`, verifica JWT, discovery, test.
- [x] **5. Media** — `POST /api/media` e `add_media`.
- [x] **5b. Via le bozze, diario e annullamento** — decisione del proprietario (sotto): `app/journal.py`,
      `/api/hub/operations`, `list_operations` / `undo_operation`.
- [ ] **6. Prova vera** — Claude e Hermes su `/mcp`, una sync vera con AnkiWeb, altro dispositivo; provare
      anche un annullamento vero (con e senza una nota modificata dopo).

### Scelte delle fasi 4 e 5

- **SDK**: `mcp>=2.3,<3` (2.3.0). La 2.x è la linea stabile (Production/Stable dalla 2.0, Python ≥ 3.10,
  provata con il 3.13 dell'immagine); `FastMCP` → `MCPServer`, e `app/main.py` entra in
  `session_manager.run()` nel lifespan (un'app montata non esegue il suo). Tetto alla 3. PyJWT[crypto] è
  dichiarata a parte (la porta già `mcp`). `requirements.lock` rigenerato: nessuna versione esistente
  è cambiata, solo aggiunte.
- **Modalità**: `stateless_http=True` (niente sessioni: un riavvio non lascia client con un
  `Mcp-Session-Id` che dà 404), risposte SSE di default. Il server parla sia il protocollo 2025-11-25
  sia il 2026-07-28 (lo sceglie l'SDK). `/mcp` e `/mcp/` sono due rotte esplicite (un `Mount` darebbe
  un 307) e `app/web.py` esclude `/mcp` e tutto `/.well-known/` dal fallback della PWA.
- **Auth fatta a mano**, non con il `TokenVerifier` dell'SDK: servono gli stessi scope, lo stesso
  rate limit e il challenge esatto richiesti da Claude. L'identità (`Identity`, kind `oauth`) arriva agli
  strumenti dalla richiesta HTTP corrente (`scope["state"]`), mai da una sessione.
- **Chi è l'utente OAuth** (il `sub` di Authentik è opaco): `preferred_username`, poi `email`; le liste
  `ANKI_OIDC_ALLOWED_USERS/_GROUPS` usano la stessa funzione del login della PWA (`oidc.authorize_claims`).
  Se le liste sono impostate e i claim mancano → 403 con un messaggio chiaro; **niente userinfo endpoint**
  (una chiamata di rete in più nel percorso della richiesta: basta aggiungere `profile`/`email` al
  provider). Senza liste decide Authentik.
- **JWT**: solo `RS256`/`ES256` (P-256), JWKS dall'URL della discovery, che deve stare sullo stesso
  origin dell'issuer (https, niente redirect, timeout 5 s, 1 MB al massimo); cache 1 h, un `kid` nuovo
  ricarica una volta al massimo al minuto, dopo un errore di rete si aspettano 10 s; con una cache
  vecchia e l'issuer giù si continua con la vecchia. Issuer irraggiungibile e nessuna cache → 503.
  Un utente non ammesso (firma valida) non conta come tentativo sbagliato, un JWT non valido sì.
- **Permessi**: ogni strumento chiama la stessa funzione della rotta REST e passa da `security.token_may`
  col percorso REST equivalente (`POST /media` è stato aggiunto alla matrice, solo write).
  `Identity.scoped` raggruppa token e OAuth; i tag riservati e `update_note` sulle sole note
  proprie sono quindi gli stessi della REST. Un token `ask_` chiamato "claude" ha lo stesso `agent::claude`
  dell'OAuth e quindi può modificarne le note: se è un problema, dai al token un altro nome.
- **Annotazioni**: `destructiveHint` solo su `update_note` (sovrascrive campi); `add_notes` è non
  distruttivo e idempotente (l'aggiornamento via `external_id` tocca solo la nota che l'agente ha creato).
- **Media**: tetto 10 MB decodificati (il trasporto MCP ha il suo tetto a 15 MB perché il base64 pesa
  1/3 in più), solo estensioni note e con la firma del contenuto coerente. **Niente SVG**: un filtro a
  espressioni regolari si aggira (`<svg/onload=…>`, entità, `href` esterni) e il file viaggerebbe con la sync;
  si usano PNG, JPG o WebP. I media escono comunque con CSP `sandbox` (`security._MEDIA_CSP`, verificato da
  `tests/test_media.py`): anche un `.svg` arrivato dalla sync e aperto a mano non esegue niente sulla nostra origine.

### Decisioni dopo la revisione indipendente

- **Blocco dei Bearer sbagliati.** Il limite per IP vale solo per le richieste che presentano un `Bearer`
  (REST e `/mcp`): la sessione col cookie non si ferma mai. Un Bearer che corrisponde a un token **revocato**
  è 401 senza contare (in `tokens.json` restano gli hash dei revocati, massimo 500, mai il chiaro); un
  token mai esistito conta. I login OIDC falliti hanno un contatore a parte che ferma solo il callback.
- **Tag riservati** (`agent::`, `ext::`, ogni variante di maiuscole e spazi): 422 da `POST /notes/tags`
  e da `PATCH /notes/{id}` della sessione se li cambiano (rimandare quelli già presenti va bene); in `remove`
  anche i genitori (`agent`, `ext`: in Anki togliere il genitore toglie i figli). Ai token con scope il
  `PATCH` li ignora in silenzio, come la creazione. `hub::` non è più riservato.
- **«Annulla» dello studio** solo per ciò che ha fatto lo studio: `_StudyUndo` (routers/study.py) ricorda
  `last_step` di Anki prima/dopo ogni risposta o azione e offre l'undo solo se da allora non è successo
  altro. Sostituisce l'elenco di etichette da escludere.
- **`tokens.json` illeggibile** → `tokens.json.bak-<timestamp>` (0600) e warning, mai sovrascritto; campi
  extra nei token ignorati (downgrade, e il vecchio `review`).
- **Limiti**: `external_id` `^[A-Za-z0-9._:-]{1,200}$` e cercato con LIKE sul tag intero; 200 KB per campo e
  2 MB per batch (422); `GET /hub/operations` `limit` ≤ 200.

### Bozze: scartate (decisione del proprietario). Rete di sicurezza con diario e undo

Il piano iniziale prevedeva una quarantena: note create come **bozze** (carte sospese, tag `hub::bozza`),
da approvare o scartare in un'Inbox della PWA, con un flag `review` per token (e `ANKI_MCP_OAUTH_REVIEW`
per l'OAuth). **Scartata**: era una strada fatta di eccezioni (modificare una nota approvata la rimetteva
in bozza, le carte nuove andavano risospese, approva e scarta dovevano essere sicuri rispetto a ciò che
l'utente aveva visto), un passaggio manuale in più per ogni carta e una fonte di note «sparite» dallo
studio. Al suo posto, **gli agenti scrivono direttamente nella collezione** (note normali e attive; la
sync, già raggruppata dopo la scrittura, fa il resto) e la rete di sicurezza è il **diario delle
operazioni con annullamento**. Sono spariti il tag `hub::bozza` (e `hub` come prefisso riservato), il flag
`review` (nei token, in `Identity`, in `tokens.json` dove i campi in più si ignorano), `ANKI_MCP_OAUTH_REVIEW`,
`HubBatchIn.draft`/`HubBatchOut.draft`, `/api/hub/drafts*`, approva/scarta, `expected_mod`/`skipped_ids`,
`HubSummary` e `GET /api/hub/summary`. Restano riservati `agent::<slug>` ed `ext::<id>` (provenienza e
idempotenza). Le note che avessero ancora il tag `hub::bozza` restano come sono.

Come funziona il diario (`backend/app/journal.py`):

- **Cosa si registra**: ogni operazione che modifica davvero la collezione — `add_notes` non-`dry_run`
  con almeno una nota creata o aggiornata (o un mazzo creato), `update_note` / `PATCH /notes/{id}` che
  cambia qualcosa, `create_deck` che crea — con `id` breve, `created_at`, `agent` (slug del token,
  «sessione» o «admin»), `kind`, `summary` in italiano e, per ogni elemento, lo stato di prima: nota
  creata → id e `mod` dopo la creazione (più un'impronta di campi e tag, perché `mod` è al secondo);
  nota aggiornata → i soli campi cambiati e i tag di prima, più `mod` e impronta dopo; mazzo creato → id
  (anche i genitori creati con lui). `dry_run`, `unchanged`, `duplicate` ed errori non si registrano.
  Niente contenuto media: solo i nomi dentro i campi.
- **Persistenza**: `<ANKI_DATA_DIR>/agent-ops.json` (0600, scrittura atomica); illeggibile → `.bak-<ts>` e
  si riparte vuoto, come `tokens.json`. Le ultime 200 operazioni e 30 giorni, più un tetto di 16 MB (le più
  vecchie si dimenticano per prime).
- **Annullamento**: sempre dentro `manager.use()` (503 con la collezione occupata), ordine dei lock
  collezione → diario. Per ogni elemento: nota creata → si cancella solo se esiste, non è cambiata e nessuna
  carta è stata studiata (`reps`, `type`, `revlog`); nota aggiornata → si ripristinano campi e tag esatti di
  prima (senza passare dal filtro dei tag riservati) solo se non è cambiata dopo; mazzo → si elimina solo se
  vuoto e senza figli. Il resto si salta con il motivo e l'operazione resta `partial`, ritentabile (gli
  elementi già annullati non si rifanno); un elemento che fallisce non ferma gli altri. Già `undone` → 409.
  Dopo un annullamento vero parte `request_soon()`. Non annulla media né sync.
- **Non confondere lo studio**: lo «Annulla» della PWA resta quello di `_StudyUndo`, che offre solo le
  operazioni dello studio; cancellare o ripristinare note sposta `last_step` e quindi non compare mai.
- **Permessi** (matrice in `security.py`, test in `test_route_matrix.py` e `test_permissions.py`):
  sessione e `ANKI_API_TOKEN` vedono e annullano tutto; un token `write` solo le proprie operazioni; un
  token `read` le elenca soltanto. Conta il tipo di accesso (`Actor.scoped`), non il nome.
- **Limiti noti**: `mod` ha la risoluzione del secondo (l'impronta del contenuto copre una modifica nello
  stesso secondo); una nota cancellata dall'utente dopo la creazione resta «saltata» (la voce rimane
  `partial`); un annullamento si propaga con la sync successiva, ma da qui non si vede cosa è successo
  alle stesse carte su un altro dispositivo non ancora sincronizzato.

## Regole per chi ci lavora

- Contratto: cambi `schemas.py` → aggiorni `types.ts` (e `client.ts`) nello stesso commit.
- Stile: italiano, sentence case, commenti sul *perché*. Rotte `def` (non `async`) che passano da
  `manager.use()`. Segreti mai nei log (`register_secret`).
- Prima di ogni commit: `pnpm typecheck && pnpm build` e `pnpm test:api`; se tocchi Dockerfile,
  `app/web.py`, dipendenze o deploy anche `docker build --network host` + `scripts/smoke-test-image.sh`.
- `git add` solo dei file della propria area; commit piccoli, Conventional Commits in italiano.
