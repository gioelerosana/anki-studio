# Anki Studio nello stack di myserv

Proposta di integrazione in `/home/ubuntu/stack`, nello stile dei servizi che ci sono già.
**Niente qui viene applicato da solo**: i file vanno copiati e le modifiche fatte a mano,
seguendo le regole dello stack (`AGENTS.md`, `docs/infrastructure/04-maintenance-updates.md`).

| File qui | Dove va nello stack |
|---|---|
| `COMPOSE/compose.anki-studio.yml` | `COMPOSE/compose.anki-studio.yml` + una riga in `include:` di `compose.yml` |
| `traefik/config/services/anki-studio.yml` | `traefik/config/services/anki-studio.yml` |
| `scripts/update-anki-studio.sh` | `scripts/update-anki-studio.sh` (facoltativo, auto-update controllato) |

Segnaposto da sostituire: `OWNER` (owner GitHub in minuscolo, nel pin dell'immagine e nello
script di update), il digest `sha256:000…` e il sottodominio `anki.jshep.xyz`.

## Cosa rispetta già

- **Immagine pinnata `tag@sha256:`**: `task validate` passa.
- **Healthcheck** nel Compose (e nell'immagine): `GET /api/health`, 200 anche durante una sync.
- **Rete edge dedicata** condivisa solo con Traefik; uscita verso AnkiWeb per la sync.
- **Hardening**: `read_only` con `/tmp` in tmpfs, `cap_drop: ALL` senza `cap_add`,
  `no-new-privileges`, utente `1000:1000` (mai root), `pids_limit`, limiti di memoria e CPU,
  log `json-file` 10m × 3.
- **Segreto** `ANKI_API_TOKEN` come Docker secret in `.secrets/` (letto con
  `ANKI_API_TOKEN_FILE`), mai nell'ambiente né nell'immagine.
- **Spegnimento**: `stop_grace_period: 120s` copre l'ultima sync con AnkiWeb.
- **Dati** in `./anki-studio/data` (bind mount) sotto Backrest.

## Integrazione, passo per passo

Prima di cominciare: pubblica la prima release (README del repo, sezione "Pubblicazione") e
annota il riferimento `ghcr.io/<owner>/anki-studio:X.Y.Z@sha256:…` dal riepilogo del workflow.

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

### 2. Segreto

```bash
cd /home/ubuntu/stack
umask 077
python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" > .secrets/anki_api_token.txt
chmod 640 .secrets/anki_api_token.txt     # gid ubuntu: il container lo legge con group_add 1001
```

Per tenere il token del deploy di prova (così la PWA già configurata non chiede niente),
copia invece il valore di `ANKI_API_TOKEN` da `/home/ubuntu/anki-studio/.env` nello stesso file,
senza a capo finale. Il token si inserisce nella PWA dalla schermata di collegamento.

Aggiungi anche `.secrets.example/anki_api_token.txt` con un valore segnaposto: `task validate`
controlla che ogni file di `.secrets.example/` esista in `.secrets/`.

### 3. Dati

```bash
mkdir -p /home/ubuntu/stack/anki-studio/data
# proprietario 1000:1000 (l'utente dell'immagine), mode 0700: serve root, oppure:
docker run --rm --network none --user 0 -v /home/ubuntu/stack/anki-studio/data:/d \
  --entrypoint sh ghcr.io/<owner>/anki-studio:X.Y.Z@sha256:… -c 'chown 1000:1000 /d && chmod 700 /d'
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
cp …/deploy/stack/traefik/config/services/anki-studio.yml traefik/config/services/
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
curl -sI https://anki.jshep.xyz/ | grep -i -E 'cache-control|content-security-policy'
docker logs anki-studio --tail 20                      # log JSON, nessun segreto
```

Su iPad: apri `https://anki.jshep.xyz` in Safari, inserisci il token, Condividi → Aggiungi
alla schermata Home. È un'origine nuova rispetto a quella di Tailscale: la PWA va
reinstallata e il token reinserito (le preferenze stanno nel `localStorage` dell'origine).
Se i dati arrivano dal deploy di prova, il collegamento AnkiWeb c'è già
(`GET /api/sync` → `logged_in: true`); altrimenti fai il login da Impostazioni → AnkiWeb.

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
IMG=ghcr.io/<owner>/anki-studio:X.Y.Z@sha256:…
mkdir -p /home/ubuntu/stack/anki-studio/data
docker run --rm --network none --user 0 \
  -v anki-studio_anki-data:/from:ro -v /home/ubuntu/stack/anki-studio/data:/to \
  --entrypoint sh "$IMG" -c 'cp -a /from/. /to/ && chown 1000:1000 /to && chmod 700 /to'

# 3. controlla la copia
docker run --rm --network none -v /home/ubuntu/stack/anki-studio/data:/d:ro --entrypoint python "$IMG" -c \
  "import sqlite3; print(sqlite3.connect('file:/d/collection.anki2?mode=ro', uri=True).execute('pragma integrity_check').fetchone())"
# → ('ok',)
sudo ls -la /home/ubuntu/stack/anki-studio/data   # collection.anki2, collection.media/, .media.db2, sync_auth.json, backups/
```

Poi i passi 4-6 sopra. **Non riavviare il deploy di prova** dopo la migrazione: due copie della
stessa collezione che sincronizzano con lo stesso account AnkiWeb si comportano come due
dispositivi con la stessa identità. Togli anche `tailscale serve` sulla 8443 se non serve più.
Tieni il volume `anki-studio_anki-data` finché il nuovo servizio non ha fatto qualche sync
senza problemi; solo allora, se vuoi: `docker compose down` in `/home/ubuntu/anki-studio` e
`docker volume rm anki-studio_anki-data`.

## Aggiornamenti

**A mano** (come gli altri servizi): nuovo tag `vX.Y.Z` nel repo → la CI pubblica l'immagine →
copia `ghcr.io/<owner>/anki-studio:X.Y.Z@sha256:…` dal riepilogo del workflow nel Compose →
`task validate` → `docker compose pull anki-studio` → `docker compose up -d --no-deps anki-studio`
→ verifica come sopra. Rollback: rimetti il pin precedente e ripeti `up -d`.

**Auto-update controllato** (facoltativo, come Hermes): `scripts/update-anki-studio.sh`
segue `:latest`, che la CI pubblica solo per le release stabili, e ripete lo stesso flusso da
solo: gate Backrest, pin `X.Y.Z@sha256:` scritto in Compose, recreate, verifica di
healthcheck, versione in `/api/health` e route pubblica, rollback automatico e notifica
Telegram. Per attivarlo:

```bash
cp …/deploy/stack/scripts/update-anki-studio.sh scripts/ && chmod +x scripts/update-anki-studio.sh
# sostituisci OWNER in IMAGE=, poi prova senza modifiche:
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
