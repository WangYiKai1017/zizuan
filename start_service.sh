#!/usr/bin/env bash
# start_service.sh - Launch the Agent Service backend (FastAPI / uvicorn).
#
# Usage:
#   ./start_service.sh [--install] [--port <PORT>] [--host <HOST>] [--no-reload] [--help]
#
# Optional environment variables:
#   VENV_PATH   If set, the script will activate the venv at this path before running.

set -e

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
HOST="0.0.0.0"
PORT="8848"
RELOAD="--reload"
DO_INSTALL="0"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$PROJECT_ROOT"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
print_help() {
    cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --install         Run 'pip install -r requirements.txt' before starting
  --port <PORT>     Override default port (default: 8000)
  --host <HOST>     Override default host (default: 0.0.0.0)
  --no-reload       Disable uvicorn auto-reload (recommended for integration tests)
  -h, --help        Show this help message and exit

Environment:
  VENV_PATH         If set, activate this virtualenv before launching
EOF
}

err() {
    echo "[start_service] ERROR: $*" >&2
}

info() {
    echo "[start_service] $*"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --install)
            DO_INSTALL="1"
            shift
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --no-reload)
            RELOAD=""
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

# ---------------------------------------------------------------------------
# Python availability
# ---------------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    err "python3 is not installed or not on PATH."
    exit 1
fi

# ---------------------------------------------------------------------------
# Optional venv activation
# ---------------------------------------------------------------------------
if [ -n "${VENV_PATH:-}" ]; then
    if [ -f "$VENV_PATH/bin/activate" ]; then
        info "Activating virtualenv at $VENV_PATH"
        # shellcheck disable=SC1090
        . "$VENV_PATH/bin/activate"
    else
        err "VENV_PATH is set ($VENV_PATH) but $VENV_PATH/bin/activate was not found."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# .env presence check
# ---------------------------------------------------------------------------
ENV_FILE="$PROJECT_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
    err ".env file not found at $ENV_FILE"
    err "Copy .env.example to .env and fill in DEEPSEEK_URL and DEEPSEEK_APIKEY."
    exit 1
fi

# ---------------------------------------------------------------------------
# Required env var presence check (grep-based, ignoring blanks/commented lines)
# ---------------------------------------------------------------------------
check_env_var() {
    local var_name="$1"
    if ! grep -E "^[[:space:]]*${var_name}[[:space:]]*=[[:space:]]*[^[:space:]].*" "$ENV_FILE" >/dev/null 2>&1; then
        err "Required variable ${var_name} is missing or empty in .env"
        return 1
    fi
}

missing=0
check_env_var "DEEPSEEK_URL"  || missing=1
check_env_var "DEEPSEEK_APIKEY" || missing=1
if [ "$missing" -ne 0 ]; then
    exit 1
fi
info "Environment check passed (.env contains DEEPSEEK_URL and DEEPSEEK_APIKEY)."

# ---------------------------------------------------------------------------
# Optional dependency install
# ---------------------------------------------------------------------------
if [ "$DO_INSTALL" = "1" ]; then
    info "Installing dependencies from requirements.txt ..."
    python3 -m pip install -r "$PROJECT_ROOT/requirements.txt"
fi

# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------
cat <<EOF

============================================================
  Agent Service - starting up
------------------------------------------------------------
  URL          : http://${HOST}:${PORT}
  Reload       : $([ -n "$RELOAD" ] && echo "enabled" || echo "disabled")
  Project root : ${PROJECT_ROOT}

  Available API route prefixes:
    - /api/interview          (start, message, end, status)
    - /api/kb-organizer       (run, result)
    - /api/biography-outline  (generate, get, confirm)
    - /api/biography-writing  (run, chapters, full)
    - /api/files              (list, tree, content)
============================================================

EOF

# ---------------------------------------------------------------------------
# Launch uvicorn
# ---------------------------------------------------------------------------
# shellcheck disable=SC2086
exec python3 -m uvicorn run_server:app --host "$HOST" --port "$PORT" $RELOAD
