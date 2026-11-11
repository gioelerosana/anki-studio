# Anki Studio nello stack di myserv

Proposta di integrazione in `/home/ubuntu/stack`, nello stile dei servizi che ci sono già.
**Niente qui viene applicato da solo**: i file vanno copiati e le modifiche fatte a mano,
seguendo le regole dello stack (`AGENTS.md`, `docs/infrastructure/04-maintenance-updates.md`).

| File qui | Dove va nello stack |
|---|---|
| `COMPOSE/compose.anki-studio.yml` | `COMPOSE/compose.anki-studio.yml` + una riga in `include:` di `compose.yml` |
| `traefik/config/services/anki-studio.yml` | `traefik/config/anki-studio.yml` (la cartella di Traefik è piatta) |
| `auth/blueprints/anki-studio-oidc.yaml` | `auth/blueprints/anki-studio-oidc.yaml` (provider e applicazione Authentik) |
| `auth/blueprints/anki-studio-mcp.yaml` | `auth/blueprints/anki-studio-mcp.yaml` (secondo provider, per il connettore di Claude: [Collegare gli agenti](#collegare-gli-agenti-claude-e-hermes)) |
| `scripts/update-anki-studio.sh` | `scripts/update-anki-studio.sh` (facoltativo, auto-update controllato) |

Il Compose è già pinnato a `ghcr.io/gioelerosana/anki-studio:26.0.1@sha256:0f84ee26…` (release
`v26.0.1`, indice multi-arch). Da adattare solo, se serve, il sottodominio `anki.jshep.xyz`.

## Cosa rispetta già

- **Immagine pinnata `tag@sha256:`**: `task validate` passa.
- **Healthcheck** nel Compose (e nell'immagine): `GET /api/health`, 200 anche durante una sync.
- **Rete edge dedicata** condivisa solo con Traefik; uscita verso AnkiWeb per la sync.
- **Hardening**: `read_only` con `/tmp` in tmpfs, `cap_drop: ALL` senza `cap_add`,
  `no-new-privileges`, utente `1000:1000` (mai root), `pids_limit`, limiti di memoria e CPU,
  log `json-file` 10m × 3.
- **Accesso con Authentik (OIDC)**, nello stile di LiteLLM: client confidenziale da blueprint,
  `smart-login-flow` (MFA/passkey), policy deny-by-default per "authentik Admins". La PWA non
  chiede token: senza sessione si viene portati su Authentik e si torna nell'app.
- **Segreto** client secret OIDC come Docker secret in `.secrets/` (letto con
  `ANKI_OIDC_CLIENT_SECRET_FILE`), mai nell'ambiente né nell'immagine.
- **Spegnimento**: `stop_grace_period: 120s` copre l'ultima sync con AnkiWeb.
- **Dati** in `./anki-studio/data` (bind mount) sotto Backrest.

## Integrazione, passo per passo

Prima di cominciare: pubblica la prima release (README del repo, sezione "Pubblicazione") e
annota il riferimento `ghcr.io/gioelerosana/anki-studio:X.Y.Z@sha256:…` dal riepilogo del workflow.

### 1. Rete

In `COMPOSE/compose.foundation.yml`, tra le reti edge (prima /28 libera di `172.30.16.0/20`,
oggi `172.30.16.208/28`: controlla che lo sia ancora):

```yaml
    edge-anki-studio:
        name: edge-anki-studio
        driver: bridge
        ipam:
            config:
                - subnet: 172.30.16.208/28
```

Poi aggiungi `edge-anki-studio` alle `networks:` di `traefik` in `COMPOSE/compose.core.yml`,
a `STACK_NETWORKS` nel `Taskfile.yml` e alla lista delle reti edge in
`docs/infrastructure/01-network-topology.md`.

L'API si fida di `X-Forwarded-For` solo dalle reti private (`FORWARDED_ALLOW_IPS` nel
Dockerfile, che include `172.16.0.0/12`): Traefik su `edge-anki-studio` è dentro, i client no.

### 2. Authentik

Provider OIDC, applicazione `anki-studio` e policy di accesso (solo superuser e "authentik
Admins") con il blueprint, come per LiteLLM (`docs/infrastructure/03-auth-authentik.md`):

```bash
cd /home/ubuntu/stack
cp …/deploy/stack/auth/blueprints/anki-studio-oidc.yaml auth/blueprints/
docker exec authentik ak apply_blueprint /blueprints/custom/anki-studio-oidc.yaml
```

Il blueprint non dichiara il client secret: Authentik lo genera alla prima applicazione.
Copialo (Admin → Applicazioni → Provider → Anki Studio → Modifica → Client Secret) nel segreto:

```bash
umask 077
printf '%s' 'IL-CLIENT-SECRET' > .secrets/anki_oidc_client_secret.txt   # senza a capo finale
chmod 640 .secrets/anki_oidc_client_secret.txt   # gid ubuntu: il container lo legge con group_add 1001
```

Aggiungi anche `.secrets.example/anki_oidc_client_secret.txt` con un valore segnaposto:
`task validate` controlla che ogni file di `.secrets.example/` esista in `.secrets/`. Se avevi
già preparato `.secrets/anki_api_token.txt` (e il suo esempio), toglili: non servono più.

Da sapere:

- **Redirect URI**: `https://anki.jshep.xyz/api/auth/callback`, `strict`. Se cambi sottodominio,
  cambiala nel blueprint e in `ANKI_PUBLIC_URL`. Per il deploy di prova (Tailscale) aggiungi la
  sua (`https://<macchina>.<tailnet>.ts.net/api/auth/callback`) come seconda voce.
- **Uscita verso `auth.jshep.xyz`**: lo scambio del codice parte dal container, come per Open
  WebUI e LiteLLM. Verifica dopo l'avvio:
  `docker exec anki-studio python -c "import urllib.request as u; print(u.urlopen('https://auth.jshep.xyz/application/o/anki-studio/.well-known/openid-configuration', timeout=5).status)"` → `200`.
- **Cambiare il client secret** su Authentik chiude tutte le sessioni della PWA (la chiave dei
  cookie ne deriva): dopo, aggiorna il file e `docker compose up -d --no-deps anki-studio`.

### 3. Dati

```bash
mkdir -p /home/ubuntu/stack/anki-studio/data
# proprietario 1000:1000 (l'utente dell'immagine), mode 0700: serve root, oppure:
docker run --rm --network none --user 0 -v /home/ubuntu/stack/anki-studio/data:/d \
  --entrypoint sh ghcr.io/gioelerosana/anki-studio:X.Y.Z@sha256:… -c 'chown 1000:1000 /d && chmod 700 /d'
```

Se vuoi portare i dati del deploy di prova, segui prima **Migrazione dei dati** qui sotto.

Aggiungi `anki-studio/` al `.gitignore` dello stack: oggi **non** è coperto (verificato con
`git check-ignore`), e contiene la collezione e la chiave di sync AnkiWeb.

### 4. Backup (Backrest)

In `COMPOSE/compose.backup.yml`, tra i volumi di `backrest`:

```yaml
            - ./anki-studio/data:/userdata/anki-studio/data:ro
```

e includi `/userdata/anki-studio/data` nel piano `MasterBackupOVH`. Dopo il cambio, fai
uno snapshot e un ripristino di prova in un percorso temporaneo.

La collezione è un database SQLite in modalità WAL che lo snapshot copia a caldo: la copia
della `collection.anki2` può risultare non coerente. Per questo il backend scrive da sé
backup coerenti in `backups/*.colpkg` (all'avvio, dopo le sync automatiche al massimo ogni
30 minuti, sempre prima di un download completo), e quelli finiscono nello snapshot. I media
sono file normali e sono comunque anche su AnkiWeb. Il ripristino è descritto in
`backend/README.md` ("Backup e ripristino").

### 5. Compose e Traefik

```bash
cp …/deploy/stack/COMPOSE/compose.anki-studio.yml COMPOSE/
cp …/deploy/stack/traefik/config/services/anki-studio.yml traefik/config/anki-studio.yml
# compose.yml: aggiungi COMPOSE/compose.anki-studio.yml alla lista di include
# Taskfile.yml: aggiungi anki-studio a SERVICES_WITH_HEALTHCHECK
task validate
docker compose up -d anki-studio
docker compose down traefik && docker compose up -d traefik   # obbligatorio a ogni cambio di Traefik
task healthcheck
```

Il record DNS: `*.jshep.xyz` copre già il sottodominio se il wildcard punta al server.

Aggiorna la tabella dei domini in `docs/infrastructure/02-routing-traefik.md`.

### 6. Verifica

```bash
curl -s https://anki.jshep.xyz/api/health              # {"ok":true,…,"version":"X.Y.Z"}
curl -s -o /dev/null -w '%{http_code}\n' https://anki.jshep.xyz/api/decks   # 401
curl -s -o /dev/null -w '%{redirect_url}\n' https://anki.jshep.xyz/api/auth/login   # https://auth.jshep.xyz/application/o/authorize/?…
curl -sI https://anki.jshep.xyz/ | grep -i -E 'cache-control|content-security-policy'
docker logs anki-studio --tail 20                      # log JSON, nessun segreto
```

Su iPad: apri `https://anki.jshep.xyz` in Safari: porta da solo su Authentik e, dopo il login,
torna nell'app. Poi Condividi → Aggiungi alla schermata Home. La PWA installata ha cookie
separati da Safari, quindi al primo avvio rifà il login (una volta: la sessione dura
`ANKI_SESSION_DAYS`, 30 giorni). È un'origine nuova rispetto a quella di Tailscale: la PWA di
prova va reinstallata.
Se i dati arrivano dal deploy di prova, il collegamento AnkiWeb c'è già
(`GET /api/sync` → `logged_in: true`); altrimenti fai il login da Impostazioni → AnkiWeb.

## Collegare gli agenti (Claude e Hermes)

Anki Studio ha un server MCP (`https://anki.jshep.xyz/mcp`, stesso container, stesso processo)
con cui gli agenti creano flashcard: entrano **subito** nella collezione (note normali e
attive, niente bozze da approvare) e poi viaggiano su AnkiWeb con la sync. Ogni loro operazione
finisce in un **diario** (`agent-ops.json` nel volume dati: ultime 200 e 30 giorni) e la annulli
dalla PWA (attività degli agenti) o l'agente stesso con `undo_operation`: cancella le note create e
rimette quelle aggiornate com'erano, ma salta ciò che hai modificato o studiato nel frattempo. Il disegno e gli strumenti sono in
[`docs/PIANO-HUB.md`](../../docs/PIANO-HUB.md). Ci sono due modi per entrare, con gli stessi
permessi dell'utente:

| Chi | Come si autentica | Cosa serve |
|---|---|---|
| **App Claude** (web, desktop, mobile) | OAuth con Authentik, secondo provider `anki-studio-mcp` | blueprint, client ID e secret incollati nel connettore |
| **Hermes Agent**, Claude Code, script | `Authorization: Bearer ask_…` | un token creato nella PWA (Impostazioni → Agenti) |

Serve un'immagine di Anki Studio che includa il server MCP (versione indicata nelle note di
release). Il Compose proposto ha già le variabili (`ANKI_MCP_*`, `ANKI_SYNC_AFTER_WRITE_SECONDS`),
il router di Traefik per `/mcp` è in `traefik/config/services/anki-studio.yml`: dopo averli
copiati, `docker compose up -d --no-deps anki-studio` ricrea il container.

### A. Authentik: secondo provider per Claude

```bash
cd /home/ubuntu/stack
cp …/deploy/stack/auth/blueprints/anki-studio-mcp.yaml auth/blueprints/
docker exec authentik ak apply_blueprint /blueprints/custom/anki-studio-mcp.yaml   # DOPO anki-studio-oidc.yaml
```

Crea provider e applicazione `anki-studio-mcp` (issuer
`https://auth.jshep.xyz/application/o/anki-studio-mcp/`) e li lega alla stessa policy della PWA
(`anki-studio-admins-only`: solo superuser e "authentik Admins"). I campi del blueprint sono
stati controllati sullo schema dei blueprint di Authentik 2026.8.5.

- **Client ID e secret**: il client ID è `anki-studio-mcp`. Il secret lo genera Authentik alla
  prima applicazione (come per la PWA, il blueprint non lo dichiara): leggilo da Admin →
  Applicazioni → Provider → Anki Studio MCP → Modifica → Client Secret (da controllare nella UI
  dove sta nella tua versione). Serve **solo a Claude**: il backend non lo usa e non va nel
  Compose né in `.secrets/`; tienine una copia nel password manager.
- **Niente registrazione dinamica (DCR)**: quella di Authentik richiede un token con lo scope
  `goauthentik.io/oidc/dcr` e crea una nuova applicazione e un nuovo provider a *ogni*
  registrazione. Per questo il client è pre-registrato e il discovery del provider non annuncia
  nessun `registration_endpoint`: non aggiungere una configurazione DCR al provider.
- **Firma**: il blueprint usa la chiave "authentik Self-signed Certificate" (RSA → RS256, con
  JWKS pubblico in `…/anki-studio-mcp/jwks/`). Per usarne un'altra cambia `signing_key` nel
  blueprint o, nella UI, Provider → Modifica → Signing Key. Senza chiave Authentik firmerebbe
  con HS256 e il backend non potrebbe verificare niente. Se la chiave fosse una EC (ES256),
  il backend deve accettarla: da controllare in Sistema → Certificati.
- **Durata**: access token **15 minuti** (Claude lo rinnova 5 minuti prima della scadenza: con
  5 minuti rinnoverebbe di continuo; un JWT non si revoca, scade), refresh token **90 giorni**
  con rotazione solo negli ultimi 30 (la connessione sopravvive a settimane di inattività e
  una risposta persa non la rompe).
- **Claim**: il backend controlla utenti e gruppi con `preferred_username` e `groups`, che
  Authentik mette nell'access token (`include_claims_in_id_token`) solo se lo scope `profile`
  è stato richiesto: lo annuncia il backend nei metadati. `aud` è il client ID.
- **Redirect URI**: solo `https://claude.ai/api/mcp/auth_callback`, `strict`, uguale per web,
  desktop e mobile (la connessione parte dal cloud di Anthropic, non dal dispositivo).

### B. Rete: cosa deve poter raggiungere Claude

Le richieste di Claude partono dall'infrastruttura di Anthropic (`160.79.104.0/21`), non dal
tuo dispositivo: il server e Authentik devono essere raggiungibili da internet. Controllato
sullo stack:

- `anki.jshep.xyz` e `auth.jshep.xyz` hanno un record A pubblico (IPv4, non Tailscale né
  privato: Claude rifiuta nomi che risolvono a indirizzi non pubblici e non usa IPv6). Il deploy
  di prova su Tailscale basta per Hermes, **non** per l'app Claude.
- Nessun WAF, CrowdSec, filtro geografico o `ipAllowList` nella configurazione di Traefik e dei
  Compose davanti ai due host (il firewall del provider cloud e nftables in ingresso non si
  vedono da qui: da controllare che la 443 sia aperta a tutta internet); il router
  `anki-studio-router` non ha forward-auth né redirect di login, e quello di Authentik ha il
  `loginRateLimit` solo sulle POST di `/api/v3/flows/executor/` (il login nel browser), non sul
  token endpoint. Se aggiungi un filtro, lascia passare `160.79.104.0/21` su `/mcp`,
  `/.well-known/` e su tutto `auth.jshep.xyz`.
- `anki-studio-mcp-router` (in `traefik/config/services/anki-studio.yml`) serve `/mcp` e
  `/.well-known/oauth-protected-resource` con la sola `securityHeaders`: niente `compress`
  (le risposte SSE dello streamable HTTP non vanno ricompresse né trattenute) e niente rate
  limit per IP, perché gli IP di Claude sono pochi e condivisi (i tentativi sbagliati li limita
  il backend). Timeout dell'entrypoint: `writeTimeout 0` e `idleTimeout 360s`, sufficienti.
- `/mcp` non deve reindirizzare: Claude perde l'header `Authorization` se il redirect cambia
  host. Usa l'URL esatto `https://anki.jshep.xyz/mcp` (senza `/` finale).
- Claude dà 10 secondi a discovery e token endpoint (30 ai refresh): `/mcp`, i metadati e
  Authentik devono rispondere subito.

Verifica da **fuori** (un'altra rete, non dal server; con il backend MCP in esecuzione):

```bash
# 401 con WWW-Authenticate (NON un 200 HTML né un redirect)
curl -si https://anki.jshep.xyz/mcp -X POST -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' -d '{}' | sed -n '1p;/^www-authenticate/Ip'
# metadati della risorsa: resource = https://anki.jshep.xyz/mcp, un solo authorization_servers
curl -s https://anki.jshep.xyz/.well-known/oauth-protected-resource
# discovery di Authentik: S256 presente, nessun registration_endpoint, offline_access tra gli scope
curl -s https://auth.jshep.xyz/application/o/anki-studio-mcp/.well-known/openid-configuration \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['issuer'], d['code_challenge_methods_supported'], d['scopes_supported'], d.get('registration_endpoint'))"
curl -s https://auth.jshep.xyz/application/o/anki-studio-mcp/jwks/ | head -c 200      # {"keys":[{"kty":"RSA",…
# con un token ask_…: initialize risponde, e lo stream non resta bufferizzato dal proxy
curl -sN https://anki.jshep.xyz/mcp -H 'Authorization: Bearer ask_…' -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

### C. App Claude (web, desktop, mobile)

1. In Claude: **Customize → Connectors → Add → Add custom connector** (a seconda della versione
   dell'app: Impostazioni → Connettori → Aggiungi connettore personalizzato; su Team ed
   Enterprise lo aggiunge un Owner da Organization settings → Connectors).
2. Nome `Anki Studio`, URL `https://anki.jshep.xyz/mcp`.
3. In **Advanced settings** (o nel secondo passaggio del dialogo): *Authentication* → *Sign in now*;
   *OAuth client* → **Use your own OAuth client**; **client ID** `anki-studio-mcp` e **client
   secret** del passo A. Non scegliere "Register automatically" né "Use Claude's published
   identity": Authentik non supporta nessuno dei due.
4. **Add**, poi **Connect**: si apre Authentik (login con MFA/passkey, `smart-login-flow`) e si
   torna in Claude. Il collegamento vale per web, desktop e mobile con lo stesso account Claude.
5. Gli strumenti si accendono per conversazione dal **+ → Connectors**. In Customize →
   Connectors → Anki Studio puoi bloccare i singoli strumenti.

Le impostazioni di autenticazione non si cambiano dopo averlo aggiunto: se ruoti il secret su
Authentik, rimuovi il connettore e aggiungilo di nuovo. Le note create da Claude hanno il tag
`agent::claude` (la provenienza) e il loro diario è quello dell'agente `claude`.

### D. Hermes Agent (e altri client con Bearer)

1. Nella PWA: **Impostazioni → Agenti**, crea un token (nome `hermes`, scope `write`). Il token `ask_…` si vede una volta sola: copialo subito.
2. Nella configurazione di Hermes (`~/.hermes/config.yaml`, nel container di myserv
   `/opt/data/config.yaml`: da controllare) aggiungi il server HTTP sotto `mcp_servers`
   (formato dalla [documentazione di Hermes](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)):

   ```yaml
   mcp_servers:
     anki:
       url: "https://anki.jshep.xyz/mcp"
       headers:
         Authorization: "Bearer ${ANKI_MCP_TOKEN}"
       timeout: 60
       connect_timeout: 30
   ```

   Hermes sostituisce `${VAR}` dalle variabili d'ambiente e da `~/.hermes/.env` (la
   documentazione lo descrive per i manifest del catalogo: se nella tua versione non lo
   sostituisce, scrivi il token in chiaro e tieni il file a `0600`). Su myserv il file `.env` di
   Hermes è dentro il dataset di backup e i segreti si passano come Docker secret
   (`scripts/hermes-secrets.sh`): usa lo stesso meccanismo per `ANKI_MCP_TOKEN` e metti il
   blocco `mcp_servers` nell'overlay gestito. `auth: oauth` non serve: per Hermes basta il Bearer.
3. Nella sessione di Hermes: `/reload-mcp` (ricarica i server MCP e l'elenco degli strumenti;
   un gateway già avviato rilegge `config.yaml` da solo in circa un minuto).
4. Prova: chiedi a Hermes di elencare i mazzi (`list_decks`).

L'URL deve essere quello pubblico: il container di Hermes sta su una rete che rifiuta gli
indirizzi privati (`untrusted_fetchers_v4`), quindi niente `http://anki-studio:8000/mcp`. Lo
stesso vale per Claude Code e gli script: `Authorization: Bearer ask_…` e mai il token
nella query string.

### E. Risoluzione dei problemi

| Sintomo | Cosa controllare |
|---|---|
| **«Couldn't reach the MCP server»** (Claude) | Non vuol dire sempre "rete": è la stessa frase per più cause. In ordine: il nome risolve a un IPv4 pubblico (`getent ahostsv4 anki.jshep.xyz` da fuori); `/mcp` risponde `401` con `WWW-Authenticate: Bearer resource_metadata=…` e non `200` (una pagina HTML = la PWA sta rispondendo al posto del server MCP: immagine senza MCP o `ANKI_MCP_ENABLED=false`) né un redirect; `/.well-known/oauth-protected-resource` risponde `200` con `resource` uguale all'URL scritto in Claude; la discovery di Authentik risponde; nessun filtro blocca `160.79.104.0/21` (cerca 403/429 in `traefik/logs/access.log` durante il tentativo). Il server non vede richieste di Claude e Authentik non vede niente: è un problema di discovery o di rete. |
| **«Authorization with the MCP server failed»** | Client ID o secret sbagliati (rimuovi e riaggiungi il connettore); redirect URI diversa da `https://claude.ai/api/mcp/auth_callback`; utente non ammesso dalla policy (Authentik → Eventi) o da `ANKI_OIDC_ALLOWED_USERS/_GROUPS`; `ANKI_MCP_OIDC_ISSUER` diverso dall'issuer reale (barra finale compresa) o `ANKI_MCP_OIDC_CLIENT_ID` diverso dal client ID (`aud`); token endpoint oltre 10 secondi. Nell'URL dell'errore c'è un `ofid_…`: ti serve per segnalarlo ad Anthropic. |
| **Il connettore funziona poi smette** | Il refresh token è scaduto (90 giorni) o revocato in Authentik, oppure hai ruotato il secret: ricollega. Un access token revocato o scaduto vale al massimo 15 minuti. |
| **`401` da Hermes o da uno script** | Header senza `Bearer `, token copiato male, token **revocato** nella PWA (Impostazioni → Agenti), oppure URL con redirect. Dopo troppi tentativi sbagliati il backend risponde `429`: aspetta. Dopo aver cambiato il token, `/reload-mcp`. |
| **`403`** | Il token ha scope `read`, o prova a modificare una nota che non porta il suo tag `agent::<nome>`. |
| **«Unexpected error while invoking tool»** | Il connettore è collegato ma lo strumento ha fallito: `docker logs anki-studio --tail 50` (log JSON, senza segreti). |
| **Le carte create non compaiono su un altro dispositivo** | Le carte entrano subito nello studio qui; sugli altri dispositivi arrivano con la sync con AnkiWeb, che parte entro `ANKI_SYNC_AFTER_WRITE_SECONDS` (30 s; `0` la spegne). Controlla `GET /api/sync` (AnkiWeb collegato? conflitto?). |
| **L'agente ha sbagliato qualcosa** | Annulla l'operazione dalla PWA (attività degli agenti) o chiedi all'agente `list_operations` e `undo_operation`. Le note che hai modificato o studiato dopo vengono saltate (con il motivo) e l'operazione resta «parziale». Non annulla i media caricati né la sync. |

### F. Sicurezza

- I token `ask_…` e l'accesso OAuth sono **dell'utente**: chi li ha scrive nella tua
  collezione. Un token ha nome e scope, si vede l'ultimo uso e si revoca dalla PWA. Per Claude
  con OAuth lo scope è `write`.
- Gli agenti **non hanno strumenti distruttivi**: niente cancellazione di note, sync completa o
  modifica dei tipi di nota. Cancellare è un gesto tuo nella PWA, con conferma (regola 1 di
  `AGENTS.md`). L'unica eccezione è `undo_operation`, che annulla solo ciò che l'agente stesso ha
  fatto (e registrato nel diario) e salta ciò che hai toccato tu. Il diario non è il backup
  della collezione: per quello ci sono i backup del volume dati.
- Il testo che un agente legge dalla collezione (`search_notes`, `get_note`) è dato non fidato
  (può contenere istruzioni): in Claude non scegliere "Always allow" se non ti fidi, e blocca
  gli strumenti che non ti servono.
- Il JWT di Authentik vale per un solo client (`aud`): il login della PWA non apre `/mcp`.
  Il client secret del connettore sta solo su Authentik e in Claude, mai nel container.
- Ogni nota creata da un agente porta il tag `agent::<nome>`: nella Libreria della PWA vedi cosa
  ha scritto chi.

## Migrazione dei dati dal deploy di prova

Il deploy di prova (`/home/ubuntu/anki-studio`, progetto compose `anki-studio`) tiene tutto
nel volume `anki-studio_anki-data`. Va **fermato prima** della copia: allo stop il backend fa
l'ultima sync con AnkiWeb e chiude la collezione, così la copia è coerente e nessuna review
resta solo lì.

```bash
# 1. ferma il deploy di prova (non `down -v`: il volume resta com'è)
cd /home/ubuntu/anki-studio
docker compose stop            # fino a 120 s: aspetta, non interrompere
docker compose logs api --tail 5      # deve esserci "Collezione chiusa"

# 2. copia il volume nella directory dello stack (stessi UID/GID: 1000)
IMG=ghcr.io/gioelerosana/anki-studio:X.Y.Z@sha256:…
mkdir -p /home/ubuntu/stack/anki-studio/data
docker run --rm --network none --user 0 \
  -v anki-studio_anki-data:/from:ro -v /home/ubuntu/stack/anki-studio/data:/to \
  --entrypoint sh "$IMG" -c 'cp -a /from/. /to/ && chown 1000:1000 /to && chmod 700 /to'

# 3. controlla la copia
docker run --rm --network none -v /home/ubuntu/stack/anki-studio/data:/d:ro --entrypoint python "$IMG" -c \
  "import sqlite3; print(sqlite3.connect('file:/d/collection.anki2?mode=ro', uri=True).execute('pragma integrity_check').fetchone())"
# → ('ok',)
sudo ls -la /home/ubuntu/stack/anki-studio/data   # collection.anki2, collection.media/, .media.db2, sync_auth.json, tokens.json, agent-ops.json, backups/
```

Poi i passi 4-6 sopra. **Non riavviare il deploy di prova** dopo la migrazione: due copie della
stessa collezione che sincronizzano con lo stesso account AnkiWeb si comportano come due
dispositivi con la stessa identità. Togli anche `tailscale serve` sulla 8443 se non serve più.
Tieni il volume `anki-studio_anki-data` finché il nuovo servizio non ha fatto qualche sync
senza problemi; solo allora, se vuoi: `docker compose down` in `/home/ubuntu/anki-studio` e
`docker volume rm anki-studio_anki-data`.

## Aggiornamenti

**A mano** (come gli altri servizi): nuovo tag `vX.Y.Z` nel repo → la CI pubblica l'immagine →
copia `ghcr.io/gioelerosana/anki-studio:X.Y.Z@sha256:…` dal riepilogo del workflow nel Compose →
`task validate` → `docker compose pull anki-studio` → `docker compose up -d --no-deps anki-studio`
→ verifica come sopra. Rollback: rimetti il pin precedente e ripeti `up -d`.

**Auto-update controllato** (facoltativo, come Hermes): `scripts/update-anki-studio.sh`
segue `:latest`, che la CI pubblica solo per le release stabili, e ripete lo stesso flusso da
solo: gate Backrest, pin `X.Y.Z@sha256:` scritto in Compose, recreate, verifica di
healthcheck, versione in `/api/health` e route pubblica, rollback automatico e notifica
Telegram. Per attivarlo:

```bash
cp …/deploy/stack/scripts/update-anki-studio.sh scripts/ && chmod +x scripts/update-anki-studio.sh
# prova senza modifiche:
scripts/update-anki-studio.sh --dry-run
# Taskfile.yml, accanto a hermes:update:
#   anki-studio:update:
#     desc: "Auto-update controllato di Anki Studio (--dry-run: task anki-studio:update -- --dry-run)"
#     cmds:
#       - "{{.STACK_DIR}}/scripts/update-anki-studio.sh {{.CLI_ARGS}}"
# crontab (dopo Hermes alle 05:15):
#   30 5 * * * /home/ubuntu/stack/scripts/update-anki-studio.sh >> /home/ubuntu/stack/logs/anki-studio-auto-update.log 2>&1 # anki-studio-auto-update
```

Lo script è stato provato su uno stack finto con un registry locale: aggiornamento, nessun
cambiamento, rollback con un'immagine che non parte. Un rollback dell'immagine non annulla una
eventuale migrazione della collezione fatta da una versione più nuova di `anki`: in quel caso
si ripristina `./anki-studio/data` dallo snapshot Backrest (o da un `.colpkg`).

Se il package GHCR è privato, `docker pull` sul server richiede un login con un token
`read:packages` (vedi README, "Pubblicazione").
