# Piano: Anki Studio come hub delle flashcard

Obiettivo: oltre a studiare, Anki Studio diventa il posto dove **arrivano le flashcard create
dagli agenti** (Claude, Hermes Agent, script) e dove le si rivede, le si cerca e le si
sistema. Poi viaggiano su AnkiWeb e da lì sugli altri dispositivi (la sync c'è già).

```
Claude (app) ──OAuth/Authentik──┐
Hermes Agent ──Bearer──────────┼─▶ /mcp (server MCP nello stesso processo) ─▶ hub.py ─▶ collezione ◀─sync─▶ AnkiWeb
script / curl ──Bearer─────────┘          REST /api/hub/*  ◀── PWA (Libreria, Inbox, Token)
```

Lo scheduler, il rendering e la sync restano quelli di Anki (regole di AGENTS.md). Il server MCP
gira **nello stesso processo** della API: la collezione è aperta una sola volta (un solo worker,
un solo `RLock`), quindi niente servizio separato.

## Concetti

- **Provenienza.** Ogni nota creata da un token riceve il tag `agent::<nome>` (nome del token in
  minuscolo, solo `a-z0-9-`).
- **Idempotenza.** L'agente può passare un `external_id`: diventa il tag `ext::<id>`. Rimandare la
  stessa nota la aggiorna (o la lascia com'è) invece di duplicarla. Il tag viaggia con la sync.
- **Bozze.** Una nota in bozza ha le carte **sospese** (non entrano nello studio) e il tag
  `hub::bozza`. Dalla PWA (Inbox) la si **approva** (carte riattivate, tag tolto) o la si
  **scarta** (cancellata, solo se è davvero una bozza). Ogni token ha `review`: se vero, le sue
  note nascono bozza e non può forzare il contrario. La sessione della PWA crea note normali.
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
| POST | `/api/hub/notes/batch` | `HubBatchIn` → `HubBatchOut`. Fino a 100 note, `dry_run`, `create_missing_decks`, `draft`. Ogni nota ha il suo esito (un errore non ferma le altre). Una batch è **una sola operazione annullabile**. | token write, sessione |
| POST | `/api/hub/decks` | `HubDeckIn` → `HubDeckOut` (idempotente) | token write, sessione |
| GET | `/api/hub/summary` | `HubSummary` (numero di bozze, per il badge) | tutti |
| GET | `/api/hub/drafts?limit&offset` | `DraftList` | tutti |
| POST | `/api/hub/drafts/approve` | `NoteIdsIn` → `DraftApproveOut` | **solo sessione** |
| POST | `/api/hub/drafts/discard` | `NoteIdsIn` → `DraftDiscardOut` (solo note con `hub::bozza`) | **solo sessione** |
| GET | `/api/cards/{id}/preview` | `CardPreview` (anche carte sospese) | tutti |
| POST | `/api/notes/{id}/move` | `NoteMoveIn` → `NoteOut` | **solo sessione** |
| DELETE | `/api/notes/{id}` | 204, cancella la nota con le sue carte | **solo sessione** |
| POST | `/api/notes/tags` | `NoteTagsIn` → `NoteTagsOut` | **solo sessione** |
| GET/POST/PATCH/DELETE | `/api/tokens[/{id}]` | `TokenOut` / `TokenIn` → `TokenCreated` / `TokenUpdate` / 204 | **solo sessione** |
| POST | `/api/media` | `MediaIn` → `MediaOut` (base64, max 10 MB, solo immagini/audio) | token write, sessione (fase 5) |

Rotte esistenti che restano: `GET /api/decks`, `/notetypes`, `/search/notes`, `/tags`, `/notes/{id}`,
`PATCH /notes/{id}`, `/sync` (stato e `POST` per sincronizzare).

### Chi può cosa

Un'identità (`require_auth`) porta con sé `kind` (`session` | `token`), `scope`, `review` e `name`.

- **Sessione della PWA** e il vecchio **`ANKI_API_TOKEN`** (compatibilità, è il token "amministratore"):
  tutto.
- **Token `read`**: solo le letture (`GET` su decks, notetypes, search/notes, tags, notes/{id},
  cards/{id}/preview, hub/summary, hub/drafts, sync).
- **Token `write`**: le letture, più `POST /hub/notes/batch`, `POST /hub/decks`, `POST /sync`,
  `POST /media` e `PATCH /notes/{id}` **solo su note con il proprio tag `agent::<nome>`**.
- Tutto il resto (cancellare, approvare, scartare, spostare, tag in blocco, token, login e
  sync completa, auth) risponde **403** a un token con scope.

I token sono `ask_` + 32 byte casuali, salvati come hash SHA-256 in `data/tokens.json` (0600,
scrittura atomica), mostrati in chiaro una volta sola, con limite ai tentativi sbagliati
(lo stesso `RateLimiter` di `ANKI_API_TOKEN`) e `last_used_at` aggiornato.

## Server MCP (`/mcp`)

Trasporto streamable HTTP, montato in `app/main.py` dal modulo `app/mcp_server.py`.
Strumenti (descrizioni in italiano, con `readOnlyHint`/`destructiveHint` corretti):

`list_decks`, `list_notetypes` (con i campi), `search_notes`, `get_note`, `add_notes` (batch,
`dry_run`), `update_note`, `create_deck`, `sync_now`, `sync_status`, `add_media`.
**Non esistono** strumenti per cancellare, approvare bozze, sync completa o tipi di nota.
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
   - Un utente autenticato via OAuth ha scope `write` con `review` acceso (impostazione
     `ANKI_MCP_OAUTH_REVIEW`, default `true`) e nome agente `claude`.
3. Mai token nella query string.

Variabili nuove: `ANKI_MCP_ENABLED` (default `true`), `ANKI_MCP_OIDC_ISSUER`,
`ANKI_MCP_OIDC_CLIENT_ID`, `ANKI_MCP_OAUTH_REVIEW`, `ANKI_SYNC_AFTER_WRITE_SECONDS`.

Per l'app Claude `/mcp` e `auth.jshep.xyz` devono essere raggiungibili da internet (gli IP di
Anthropic sono `160.79.104.0/21`), senza WAF o filtri geografici in mezzo, e discovery, registrazione
e token endpoint hanno 10 secondi di tempo. Il deploy di prova su Tailscale basta per Hermes, non
per l'app Claude.

## PWA

- **Libreria** (`#/library`): ricerca con la sintassi di Anki, filtri rapidi per mazzo, tag, agente
  e "solo bozze"; anteprima della carta (`CardPreview`, in Shadow DOM come lo studio); modifica,
  sposta, tag in blocco, cancella con conferma.
- **Inbox** (`#/inbox`): le bozze con anteprima; approva, modifica, scarta (con conferma), anche
  in blocco. Badge sul tasto nella schermata dei mazzi (`GET /api/hub/summary`).
- **Impostazioni → Agenti**: token (crea → mostra una volta e copia, `scope`, `review`, revoca,
  ultimo uso) e come collegare Claude e Hermes.

## Fasi

- [ ] **1. Backend REST per gli agenti** — `app/hub.py`, `routers/hub.py`, token con scope e
      `review`, bozze, sync dopo la scrittura, test.
- [ ] **2. PWA: Libreria, Inbox, Agenti** — contro il contratto sopra.
- [ ] **3. Deploy e Authentik** — blueprint del secondo provider, Traefik per `/mcp` e
      `.well-known`, variabili, guide di collegamento per Claude e Hermes.
- [ ] **4. Server MCP + OAuth** — `app/mcp_server.py`, verifica JWT, discovery, test.
- [ ] **5. Media** — `POST /api/media` e `add_media`.
- [ ] **6. Prova vera** — Claude e Hermes su `/mcp`, una sync vera con AnkiWeb, altro dispositivo.

## Regole per chi ci lavora

- Contratto: cambi `schemas.py` → aggiorni `types.ts` (e `client.ts`) nello stesso commit.
- Stile: italiano, sentence case, commenti sul *perché*. Rotte `def` (non `async`) che passano da
  `manager.use()`. Segreti mai nei log (`register_secret`).
- Prima di ogni commit: `pnpm typecheck && pnpm build` e `pnpm test:api`; se tocchi Dockerfile,
  `app/web.py`, dipendenze o deploy anche `docker build --network host` + `scripts/smoke-test-image.sh`.
- `git add` solo dei file della propria area; commit piccoli, Conventional Commits in italiano.
