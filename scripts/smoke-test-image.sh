#!/usr/bin/env bash
# Avvio di prova dell'immagine con lo stesso hardening previsto nello stack:
# read_only + tmpfs, cap_drop ALL, no-new-privileges, utente non root, token come
# Docker secret (ANKI_API_TOKEN_FILE). Controlla healthcheck, PWA, header, token,
# confine /api e spegnimento pulito (sync finale + collezione chiusa).
#
#   scripts/smoke-test-image.sh anki-studio:local            # porta 18080
#   PORT=18181 scripts/smoke-test-image.sh ghcr.io/gioelerosana/anki-studio:26.0.1
#
# Usa un container, una rete e un volume usa e getta con un nome suo: non tocca
# nessun altro progetto compose né i volumi esistenti. Lo usa anche la CI.
set -euo pipefail

IMAGE=${1:?uso: $0 <immagine>}
PORT=${PORT:-18080}
NAME="anki-studio-smoke-$$"
BASE="http://127.0.0.1:$PORT"
TMP=$(mktemp -d)
FAILED=0

cleanup() {
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker network rm "$NAME" >/dev/null 2>&1 || true
    docker volume rm "$NAME-data" >/dev/null 2>&1 || true
    rm -rf "$TMP"
}
trap cleanup EXIT

ok() { echo "  OK   $*"; }
ko() { echo "  FAIL $*"; FAILED=$((FAILED + 1)); }
check() { # check <descrizione> <atteso> <ottenuto>
    if [ "$2" = "$3" ]; then ok "$1"; else ko "$1 (atteso '$2', ottenuto '$3')"; fi
}
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
header() { # header <nome> <url> [curl args]: valore dell'header della risposta GET
    local name=$1 url=$2; shift 2
    curl -s -o /dev/null -D - "$@" "$url" | tr -d '\r' \
        | awk -v n="$(echo "$name" | tr '[:upper:]' '[:lower:]')" \
            'BEGIN{IGNORECASE=1} tolower($0) ~ "^"n":" {sub(/^[^:]*:[ ]*/, ""); print; exit}'
}

python3 -c 'import secrets; print(secrets.token_urlsafe(32), end="")' > "$TMP/token"
chmod 444 "$TMP/token"
TOKEN=$(cat "$TMP/token")

# rete dedicata: su myserv il bridge di default è disattivato ("bridge": "none")
docker network create "$NAME" >/dev/null
docker run -d --name "$NAME" --network "$NAME" \
    -p "127.0.0.1:$PORT:8000" \
    --read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
    --cap-drop ALL --security-opt no-new-privileges:true \
    --pids-limit 256 --memory 1g \
    --stop-timeout 120 \
    -e ANKI_API_TOKEN_FILE=/run/secrets/anki_api_token \
    -e ANKI_SYNC_ON_STARTUP=false -e ANKI_AUTO_SYNC_MINUTES=0 \
    -v "$TMP/token:/run/secrets/anki_api_token:ro" \
    -v "$NAME-data:/data" \
    "$IMAGE" >/dev/null

echo "== $IMAGE su $BASE"
echo "-- healthcheck"
for _ in $(seq 1 60); do
    HEALTH=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$NAME")
    [ "$HEALTH" = "healthy" ] && break
    [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" = "true" ] || break
    sleep 2
done
check "healthcheck dell'immagine" healthy "$HEALTH"
if [ "$HEALTH" != "healthy" ]; then
    docker logs "$NAME" 2>&1 | tail -30
    exit 1
fi

echo "-- processo e filesystem"
check "utente non root" "1000:1000" "$(docker exec "$NAME" sh -c 'echo "$(id -u):$(id -g)"')"
case "$(docker exec "$NAME" sh -c "tr '\\0' ' ' < /proc/1/cmdline")" in
    *uvicorn*"--workers 1"*) ok "PID 1 è uvicorn con un solo worker" ;;
    *) ko "PID 1 non è uvicorn con --workers 1" ;;
esac
if docker exec "$NAME" sh -c 'touch /srv/app/x' 2>/dev/null; then ko "/srv scrivibile"; else ok "filesystem in sola lettura"; fi
check "/data scrivibile e con la collezione" "yes" "$(docker exec "$NAME" sh -c 'test -w /data && test -f /data/collection.anki2 && echo yes')"

echo "-- PWA"
check "GET / 200" 200 "$(status "$BASE/")"
check "index.html no-cache" "no-cache" "$(header Cache-Control "$BASE/")"
check "index.html X-Frame-Options" "DENY" "$(header X-Frame-Options "$BASE/")"
check "index.html nosniff" "nosniff" "$(header X-Content-Type-Options "$BASE/")"
case "$(header Content-Security-Policy "$BASE/")" in
    *"script-src 'self' 'sha256-"*) ok "CSP della shell con l'hash dello script inline" ;;
    *) ko "CSP della shell mancante" ;;
esac
curl -s "$BASE/" | grep -q '<div id="root">' && ok "è la PWA" || ko "GET / non è la PWA"
check "fallback SPA" 200 "$(status "$BASE/decks/123")"
check "sw.js no-cache" "no-cache" "$(header Cache-Control "$BASE/sw.js")"
check "manifest no-cache" "no-cache" "$(header Cache-Control "$BASE/manifest.webmanifest")"
ASSET=$(curl -s "$BASE/" | grep -o '/assets/[^"]*\.js' | head -1)
check "asset $ASSET 200" 200 "$(status "$BASE$ASSET")"
check "asset immutable" "public, max-age=31536000, immutable" "$(header Cache-Control "$BASE$ASSET")"
check "asset mancante 404" 404 "$(status "$BASE/assets/non-esiste.js")"
check "POST sulla PWA 405" 405 "$(status -X POST "$BASE/")"
check "/docs non esposto (è la PWA)" "no-cache" "$(header Cache-Control "$BASE/docs")"

echo "-- API"
HEALTH_JSON=$(curl -s "$BASE/api/health")
echo "     /api/health: $HEALTH_JSON"
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); sys.exit(0 if d["ok"] and d["version"] else 1)' "$HEALTH_JSON" \
    && ok "/api/health ok con la versione" || ko "/api/health"
check "/api/decks senza token 401" 401 "$(status "$BASE/api/decks")"
check "/api/decks con token sbagliato 401" 401 "$(status -H 'Authorization: Bearer sbagliato-sbagliato' "$BASE/api/decks")"
check "/api/decks con token 200" 200 "$(status -H "Authorization: Bearer $TOKEN" "$BASE/api/decks")"
check "/api no-store" "no-store" "$(header Cache-Control "$BASE/api/decks" -H "Authorization: Bearer $TOKEN")"
check "/api inesistente 404 (non la PWA)" 404 "$(status -H "Authorization: Bearer $TOKEN" "$BASE/api/non-esiste")"
check "body oltre 50 MB 413" 413 "$(head -c 52428900 /dev/zero | status -X POST -H 'Content-Type: application/json' --data-binary @- "$BASE/api/notes")"

echo "-- spegnimento"
docker stop -t 120 "$NAME" >/dev/null
check "uscita pulita" 0 "$(docker inspect -f '{{.State.ExitCode}}' "$NAME")"
LOGS=$(docker logs "$NAME" 2>&1)
echo "$LOGS" | grep -q "Collezione chiusa" && ok "collezione chiusa allo spegnimento" || ko "collezione non chiusa"
echo "$LOGS" | grep -qF "$TOKEN" && ko "il token compare nei log" || ok "nessun token nei log"
if docker image inspect "$IMAGE" --format '{{json .Config.Env}}' | grep -qF "$TOKEN"; then ko "token nell'immagine"; fi

echo
if [ "$FAILED" -gt 0 ]; then
    echo "== $FAILED controlli falliti"
    docker logs "$NAME" 2>&1 | tail -30
    exit 1
fi
echo "== tutti i controlli passati"
