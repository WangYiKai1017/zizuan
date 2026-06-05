#!/usr/bin/env bash
# Start the local debug HTML panel and the FastAPI backend it talks to.
#
# Usage:
#   ./start_debug_frontend.sh
#   ./start_debug_frontend.sh --no-open
#   ./start_debug_frontend.sh --backend-port 8000 --frontend-port 8081

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="8081"
OPEN_BROWSER="1"
LOG_DIR="$PROJECT_ROOT/logs"

print_help() {
    cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --backend-port <PORT>   Backend API port (default: 8000)
  --frontend-port <PORT>  Debug HTML port (default: 8081)
  --no-open               Do not open the browser automatically
  -h, --help              Show this help message

URLs:
  Backend health: http://${BACKEND_HOST}:${BACKEND_PORT}/health
  Debug panel   : http://${FRONTEND_HOST}:${FRONTEND_PORT}/debug_frontend.html
EOF
}

info() {
    echo "[debug] $*"
}

err() {
    echo "[debug] ERROR: $*" >&2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --backend-port)
            BACKEND_PORT="${2:-}"
            shift 2
            ;;
        --frontend-port)
            FRONTEND_PORT="${2:-}"
            shift 2
            ;;
        --no-open)
            OPEN_BROWSER="0"
            shift
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            err "Unknown argument: $1"
            print_help
            exit 1
            ;;
    esac
done

BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
HEALTH_URL="${BACKEND_URL}/health"
DEBUG_URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}/debug_frontend.html"

cd "$PROJECT_ROOT"

if [ ! -x "$PYTHON" ]; then
    err "Virtualenv Python not found at $PYTHON"
    err "Create the project virtualenv before running this script."
    exit 1
fi

if [ ! -f "$PROJECT_ROOT/debug_frontend.html" ]; then
    err "debug_frontend.html not found in $PROJECT_ROOT"
    exit 1
fi

mkdir -p "$LOG_DIR"

url_ok() {
    "$PYTHON" - "$1" <<'PY'
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=1.5) as response:
        raise SystemExit(0 if 200 <= response.status < 500 else 1)
except Exception:
    raise SystemExit(1)
PY
}

wait_for_url() {
    local url="$1"
    local label="$2"
    local tries=30

    while [ "$tries" -gt 0 ]; do
        if url_ok "$url"; then
            return 0
        fi
        tries=$((tries - 1))
        sleep 0.5
    done

    err "$label did not become ready: $url"
    return 1
}

start_backend() {
    if url_ok "$HEALTH_URL"; then
        info "Backend already running: $HEALTH_URL"
        return 0
    fi

    info "Starting backend on ${BACKEND_HOST}:${BACKEND_PORT}"
    nohup "$PYTHON" -m uvicorn run_server:app \
        --host "$BACKEND_HOST" \
        --port "$BACKEND_PORT" \
        --reload \
        > "$LOG_DIR/debug-backend.log" 2>&1 &
    echo "$!" > "$LOG_DIR/debug-backend.pid"

    wait_for_url "$HEALTH_URL" "Backend"
}

start_frontend() {
    if url_ok "$DEBUG_URL"; then
        info "Debug panel already running: $DEBUG_URL"
        return 0
    fi

    info "Starting debug panel on ${FRONTEND_HOST}:${FRONTEND_PORT}"
    nohup "$PYTHON" -m http.server "$FRONTEND_PORT" --bind "$FRONTEND_HOST" \
        > "$LOG_DIR/debug-frontend.log" 2>&1 &
    echo "$!" > "$LOG_DIR/debug-frontend.pid"

    wait_for_url "$DEBUG_URL" "Debug panel"
}

start_backend
start_frontend

cat <<EOF

Debug panel is ready:
  ${DEBUG_URL}

Backend health:
  ${HEALTH_URL}

Logs:
  ${LOG_DIR}/debug-backend.log
  ${LOG_DIR}/debug-frontend.log

EOF

if [ "$OPEN_BROWSER" = "1" ]; then
    if command -v open >/dev/null 2>&1; then
        open "$DEBUG_URL"
    else
        info "Browser auto-open is not available on this system."
    fi
fi
