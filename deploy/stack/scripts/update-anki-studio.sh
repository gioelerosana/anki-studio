#!/bin/bash
# Auto-update controllato di Anki Studio (job dell'host, cron), sul modello di
# scripts/update-hermes.sh dello stack. PROPOSTA: da copiare in /home/ubuntu/stack/scripts/
# e da attivare a mano (vedi deploy/stack/README.md nel repo anki-studio).
#
# Vincoli (docs/infrastructure/04-maintenance-updates.md):
#   - Il container non si aggiorna da solo; niente docker.sock dentro Anki Studio.
#   - Il pin in Compose resta tag + digest: `task validate` continua a passare.
#   - Solo canale stabile: ghcr.io/gioelerosana/anki-studio:latest, che la CI pubblica solo
#     per i tag vX.Y.Z senza suffisso (mai le -rc). Il pin usa il tag di versione letto
#     dalla label org.opencontainers.image.version dell'immagine.
#   - Rollback = pin precedente in Compose + recreate; l'immagine precedente resta su
#     disco e il suo riferimento va in state/update-bot/anki-studio-last-known-good.txt.
#   - Il rollback dell'immagine non annulla una migrazione della collezione fatta da una
#     versione più nuova di `anki`: i dati si recuperano dallo snapshot Backrest di
#     ./anki-studio/data o dai backup .colpkg in ./anki-studio/data/backups/.
#
# Lo stop del container vecchio (docker compose up -d → SIGTERM, stop_grace_period 120 s)
# fa da sé l'ultima sync con AnkiWeb e chiude la collezione: niente review perse.
#
# Flusso: lock -> gate Backrest -> baseline -> pull :latest -> confronto digest ->
#   pin in Compose -> recreate -> verifica (healthcheck + versione in /api/health +
#   route pubblica) -> notifica. Ogni verifica fallita fa il rollback.
#
# Uso:
#   update-anki-studio.sh            # giro completo (cron)
#   update-anki-studio.sh --dry-run  # gate + pull + confronto, nessuna modifica
#
# Log: logs/anki-studio-auto-update.log (redirect del cron)
# Stato: state/update-bot/anki-studio-last-result.json

set -u -o pipefail

export PATH="/usr/local/bin:/usr/bin:/bin"

STACK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$STACK_DIR" || exit 1

IMAGE="ghcr.io/gioelerosana/anki-studio" # in minuscolo, come lo pubblica la CI
CHANNEL="latest"                  # solo release stabili
COMPOSE_FILE="$STACK_DIR/COMPOSE/compose.anki-studio.yml"
SERVICE="anki-studio"
LAST_KNOWN_GOOD="$STACK_DIR/state/update-bot/anki-studio-last-known-good.txt"
LAST_RESULT="$STACK_DIR/state/update-bot/anki-studio-last-result.json"
PUBLIC_URL="https://anki.jshep.xyz/api/health"
HEALTH_TIMEOUT_S=240
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

IMAGE_RE="^[[:space:]]*image:[[:space:]]*${IMAGE//./\\.}:"

log() { echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*"; }
notify() {
    log "TELEGRAM: $1"
    "$STACK_DIR/scripts/notify-telegram.sh" "$1" >/dev/null 2>&1 || true
}
write_result() {
    python3 - "$LAST_RESULT" "$1" "$2" "${PIN_NEW:-}" "${PIN_CURRENT:-}" <<'PY' 2>/dev/null || true
import json, sys, time
path, status, detail, new, cur = sys.argv[1:6]
data = {}
try:
    with open(path) as f:
        data = json.load(f)
except Exception:
    pass
data.update({
    "status": status,
    "detail": detail,
    "new_ref": new,
    "previous_ref": cur,
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
})
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PY
}
die() { # interrompe senza modifiche (o con il rollback già fatto)
    log "ABORT: $1"
    write_result "aborted" "$1"
    notify "Anki Studio auto-update interrotto: $1"
    exit 1
}
set_pin() { # set_pin <riferimento completo>
    python3 - "$COMPOSE_FILE" "$1" "$IMAGE" <<'PY'
import re, sys
path, ref, image = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    lines = f.readlines()
pat = re.compile(r"^\s*image:\s*" + re.escape(image) + ":")
idx = [i for i, l in enumerate(lines) if pat.match(l)]
assert len(idx) == 1, f"expected 1 image line, found {len(idx)}"
indent = re.match(r"^(\s*)", lines[idx[0]]).group(1)
lines[idx[0]] = f"{indent}image: {ref}\n"
with open(path, "w") as f:
    f.writelines(lines)
PY
}
container() { docker compose ps -q "$SERVICE" 2>/dev/null; }
health_status() {
    docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' \
        "$(container)" 2>/dev/null || echo missing
}
wait_healthy() {
    local timeout=${1:-240} elapsed=0 status
    while [ "$elapsed" -lt "$timeout" ]; do
        # un container che si riavvia (es. errore all'avvio) non diventerà sano:
        # inutile aspettare tutto il timeout
        if [ "$(docker inspect -f '{{.RestartCount}}' "$(container)" 2>/dev/null || echo 0)" -gt 0 ]; then
            return 1
        fi
        status=$(health_status)
        case "$status" in
            healthy) return 0 ;;
            missing | stopped | no-healthcheck) return 1 ;;
        esac
        sleep 5
        elapsed=$((elapsed + 5))
    done
    return 1
}
# versione che il container in esecuzione dichiara in /api/health
running_version() {
    docker exec "$SERVICE" python -c 'import json, urllib.request as u; print(json.load(u.urlopen("http://127.0.0.1:8000/api/health", timeout=5))["version"])' 2>/dev/null || true
}

# ─── Lock ────────────────────────────────────────────────────────────────
mkdir -p "$STACK_DIR/state/update-bot"
exec 9>"$STACK_DIR/state/anki-studio-update.lock"
if ! flock -n 9; then
    log "Another anki-studio update is already running; exiting."
    exit 0
fi

log "=== Anki Studio controlled auto-update start (dry_run=$DRY_RUN) ==="

# ─── Gate Backrest ───────────────────────────────────────────────────────
# Prudenza: si aggiorna solo con Backrest attivo, così lo snapshot di
# ./anki-studio/data continua a girare e resta il punto di ripristino dei dati.
BACKREST_STATE=$(docker inspect -f '{{.State.Running}}' backrest 2>/dev/null || echo false)
[ "$BACKREST_STATE" = "true" ] || die "Backrest container is not running; skipping update"
log "Backrest liveness: running"

# ─── Pin attuale ─────────────────────────────────────────────────────────
[ "$(grep -cE "$IMAGE_RE" "$COMPOSE_FILE")" = "1" ] \
    || die "expected exactly one $IMAGE pin in $COMPOSE_FILE"
PIN_CURRENT=$(grep -E "$IMAGE_RE" "$COMPOSE_FILE" | head -1 | sed 's/^[[:space:]]*image:[[:space:]]*//')
[ -n "$PIN_CURRENT" ] || die "cannot read current image pin"
CURRENT_DIGEST="${PIN_CURRENT##*@sha256:}"
log "Current pin: $PIN_CURRENT"

# ─── Baseline ────────────────────────────────────────────────────────────
docker info >/dev/null 2>&1 || die "Docker daemon unreachable"
[ -n "$(container)" ] || die "no container for service $SERVICE"
BASE_HEALTH=$(health_status)
[ "$BASE_HEALTH" = "healthy" ] || die "anki-studio is not healthy before update (status: $BASE_HEALTH); refusing to update a broken service"

# una route pubblica già rotta prima dell'aggiornamento non può giudicarlo
PUBLIC_BASELINE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$PUBLIC_URL" || echo 000)
PUBLIC_GATE=1
if [ "$PUBLIC_BASELINE" = "200" ]; then
    log "Public route baseline: HTTP $PUBLIC_BASELINE"
else
    PUBLIC_GATE=0
    log "WARNING: public route baseline HTTP $PUBLIC_BASELINE; route check will not gate this update"
fi

# ─── Pull del canale stabile, digest e versione ──────────────────────────
log "Pulling $IMAGE:$CHANNEL (stable)..."
docker pull -q "$IMAGE:$CHANNEL" >/dev/null 2>&1 || die "docker pull $IMAGE:$CHANNEL failed"
NEW_DIGEST=$(docker image inspect --format '{{json .RepoDigests}}' "$IMAGE:$CHANNEL" | python3 -c '
import json, sys
image = sys.argv[1]
digests = json.load(sys.stdin)
mine = [d for d in digests if d.startswith(image + "@sha256:")]
print(mine[0].split("@sha256:", 1)[1] if mine else "")
' "$IMAGE")
[ -n "$NEW_DIGEST" ] || die "cannot resolve digest of $IMAGE:$CHANNEL"
log "Channel digest: sha256:$NEW_DIGEST"

if [ "$NEW_DIGEST" = "$CURRENT_DIGEST" ]; then
    log "Anki Studio is already at the latest stable release. Nothing to do."
    write_result "up-to-date" "digest unchanged"
    exit 0
fi

NEW_VERSION=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "$IMAGE:$CHANNEL" 2>/dev/null || true)
[[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "unexpected version label '$NEW_VERSION' on $IMAGE:$CHANNEL"
PIN_NEW="$IMAGE:$NEW_VERSION@sha256:$NEW_DIGEST"
log "New pin: $PIN_NEW"
write_result "in-progress" "updating"

if [ "$DRY_RUN" = "1" ]; then
    log "DRY-RUN: would update $COMPOSE_FILE to $PIN_NEW, recreate $SERVICE and verify."
    write_result "dry-run" "update available"
    exit 0
fi

# ─── Pin in Compose (tag + digest) ───────────────────────────────────────
cp "$COMPOSE_FILE" "$COMPOSE_FILE.bak-update"
set_pin "$PIN_NEW" || { cp "$COMPOSE_FILE.bak-update" "$COMPOSE_FILE"; die "cannot rewrite pin"; }
docker compose --profile '*' config --quiet 2>/dev/null || {
    cp "$COMPOSE_FILE.bak-update" "$COMPOSE_FILE"
    die "compose config invalid after pin update; pin restored"
}
grep -Fq "@sha256:$NEW_DIGEST" "$COMPOSE_FILE" || {
    cp "$COMPOSE_FILE.bak-update" "$COMPOSE_FILE"
    die "pin update not reflected in $COMPOSE_FILE; pin restored"
}
log "Compose pin updated: $PIN_NEW"

# ─── Applica ─────────────────────────────────────────────────────────────
rollback() {
    log "ROLLBACK: restoring $PIN_CURRENT"
    set_pin "$PIN_CURRENT"
    if docker compose up -d --no-deps "$SERVICE" >/dev/null 2>&1; then
        if wait_healthy 180; then
            log "Rollback applied and healthy."
        else
            log "CRITICAL: rollback container is not healthy; manual intervention required (collection migrated by the new version? restore ./anki-studio/data from Backrest)"
        fi
    else
        log "CRITICAL: rollback recreate failed; manual intervention required"
    fi
    write_result "rolled-back" "update failed, previous image restored"
    notify "Anki Studio auto-update FALLITO, eseguito rollback a $PIN_CURRENT. Dettagli: logs/anki-studio-auto-update.log"
    exit 1
}

if ! docker compose pull "$SERVICE" >/dev/null 2>&1; then
    log "Pinned pull failed; image already local from the channel pull. Continuing with recreate."
fi
# SIGTERM al container vecchio: ultima sync con AnkiWeb e chiusura della collezione
docker compose up -d --no-deps "$SERVICE" >/dev/null || rollback

# ─── Verifica ────────────────────────────────────────────────────────────
log "Waiting for healthcheck (max ${HEALTH_TIMEOUT_S}s)..."
if ! wait_healthy "$HEALTH_TIMEOUT_S"; then
    log "Verification FAILED: healthcheck"
    rollback
fi
log "Healthcheck: healthy"

RUNNING=$(running_version)
if [ "$RUNNING" != "$NEW_VERSION" ]; then
    log "Verification FAILED: /api/health reports version '$RUNNING', expected $NEW_VERSION"
    rollback
fi
log "Version in /api/health: $RUNNING"

if [ "$PUBLIC_GATE" = "1" ]; then
    PUBLIC_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$PUBLIC_URL" || echo 000)
    if [ "$PUBLIC_CODE" != "200" ]; then
        log "Verification FAILED: public route HTTP $PUBLIC_CODE (was $PUBLIC_BASELINE before update)"
        rollback
    fi
    log "Public route: HTTP $PUBLIC_CODE"
fi

# ─── Fatto ───────────────────────────────────────────────────────────────
printf '%s\n' "$PIN_CURRENT" > "$LAST_KNOWN_GOOD"
log "Last known good recorded: $PIN_CURRENT"
write_result "updated" "ok"
log "=== Anki Studio updated: $PIN_CURRENT -> $PIN_NEW ==="
notify "Anki Studio aggiornato: ${PIN_CURRENT%%@*} -> ${PIN_NEW%%@*} (sha256 ${NEW_DIGEST:0:12}). Healthcheck/versione/route OK. Rollback ref: state/update-bot/anki-studio-last-known-good.txt"
exit 0
