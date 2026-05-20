#!/usr/bin/env bash
# setup.sh - One-click cloud deployment setup for the Agent Service.
# Creates venv, installs deps, validates environment, and prints launch instructions.
set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
REQ_FILE="requirements.txt"
REQ_DEV_FILE="requirements-dev.txt"
ENV_FILE=".env"
ENV_EXAMPLE=".env.example"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=9

# ---------------------------------------------------------------------------
# Defaults (flags)
# ---------------------------------------------------------------------------
INSTALL_DEV=0
VERBOSE=0
SKIP_VENV=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
banner() {
    echo ""
    echo "============================================================"
    echo "  Elder Memoir Agent Service - Cloud Setup"
    echo "============================================================"
    echo ""
}

print_help() {
    cat <<EOF
Usage: $(basename "$0") [options]

One-click setup script for cloud deployment of the Agent Service.
Creates a virtual environment, installs dependencies, validates the
environment, and prints instructions to start the service.

Options:
  --dev         Also install development dependencies (pytest, etc.)
  --verbose     Show full pip install output (default: quiet)
  --no-venv     Skip venv creation/activation (e.g., inside Docker)
  -h, --help    Show this help message and exit

This script is idempotent — safe to re-run at any time.
EOF
}

info() { echo "[setup] $*"; }
warn() { echo "[setup] WARNING: $*" >&2; }
err()  { echo "[setup] ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --dev)      INSTALL_DEV=1; shift ;;
        --verbose)  VERBOSE=1; shift ;;
        --no-venv)  SKIP_VENV=1; shift ;;
        -h|--help)  print_help; exit 0 ;;
        *)
            err "Unknown argument: $1"
            print_help
            exit 1
            ;;
    esac
done

banner

# ---------------------------------------------------------------------------
# Step 1: Detect Python
# ---------------------------------------------------------------------------
info "Detecting Python interpreter..."

PYTHON=""
for candidate in python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    err "No suitable Python interpreter found (need python3 >= ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR})."
    err "Please install Python 3.10+ and ensure it is on PATH."
    exit 1
fi

# Verify version meets minimum
PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt "$MIN_PYTHON_MAJOR" ] || { [ "$PY_MAJOR" -eq "$MIN_PYTHON_MAJOR" ] && [ "$PY_MINOR" -lt "$MIN_PYTHON_MINOR" ]; }; then
    err "Python ${PY_VERSION} found but >= ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR} is required."
    exit 1
fi

info "Using $PYTHON (version $PY_VERSION)"

# ---------------------------------------------------------------------------
# Step 2: Detect / bootstrap pip
# ---------------------------------------------------------------------------
if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
    info "pip not found — attempting to bootstrap via ensurepip..."
    "$PYTHON" -m ensurepip --default-pip || {
        err "Could not install pip. Please install pip manually."
        exit 1
    }
fi

# ---------------------------------------------------------------------------
# Step 3: Create / activate venv
# ---------------------------------------------------------------------------
if [ "$SKIP_VENV" -eq 0 ]; then
    if [ ! -d "$VENV_DIR" ]; then
        info "Creating virtual environment at ./${VENV_DIR} ..."
        "$PYTHON" -m venv "$VENV_DIR"
    else
        info "Reusing existing virtual environment at ./${VENV_DIR}"
    fi

    # Activate
    # shellcheck disable=SC1091
    . "$VENV_DIR/bin/activate"
    info "Virtual environment activated."
else
    info "Skipping venv (--no-venv)."
fi

# ---------------------------------------------------------------------------
# Step 4: Upgrade pip + build tools
# ---------------------------------------------------------------------------
PIP_QUIET=""
if [ "$VERBOSE" -eq 0 ]; then
    PIP_QUIET="--quiet"
fi

info "Upgrading pip, setuptools, wheel..."
# shellcheck disable=SC2086
pip install --upgrade pip setuptools wheel $PIP_QUIET

# ---------------------------------------------------------------------------
# Step 5: Install requirements
# ---------------------------------------------------------------------------
info "Installing production dependencies from ${REQ_FILE}..."
# shellcheck disable=SC2086
pip install -r "$REQ_FILE" $PIP_QUIET

if [ "$INSTALL_DEV" -eq 1 ]; then
    info "Installing development dependencies from ${REQ_DEV_FILE}..."
    # shellcheck disable=SC2086
    pip install -r "$REQ_DEV_FILE" $PIP_QUIET
fi

# ---------------------------------------------------------------------------
# Step 6: .env handling
# ---------------------------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$ENV_EXAMPLE" ]; then
        info "Copying ${ENV_EXAMPLE} -> ${ENV_FILE}"
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        warn "Created .env from .env.example — you MUST fill in DEEPSEEK_URL and DEEPSEEK_APIKEY."
    else
        err "Neither ${ENV_FILE} nor ${ENV_EXAMPLE} found. Cannot configure environment."
        err "Please create a .env file with DEEPSEEK_URL and DEEPSEEK_APIKEY."
        exit 1
    fi
else
    info ".env file already exists — not overwriting."
fi

# ---------------------------------------------------------------------------
# Step 7: Validate environment variables (warn, do not fail)
# ---------------------------------------------------------------------------
check_env_var() {
    local var_name="$1"
    local val
    val=$(grep -E "^[[:space:]]*${var_name}[[:space:]]*=" "$ENV_FILE" 2>/dev/null | head -1 | sed "s/^[^=]*=//;s/^[[:space:]]*//;s/[[:space:]]*$//" || true)
    if [ -z "$val" ] || [ "$val" = "your_api_key_here" ]; then
        warn "${var_name} is missing or has a placeholder value in .env"
        warn "  (Cloud deployments may inject env vars at runtime — this is not fatal.)"
        return 1
    fi
    return 0
}

env_ok=1
check_env_var "DEEPSEEK_URL" || env_ok=0
check_env_var "DEEPSEEK_APIKEY" || env_ok=0

if [ "$env_ok" -eq 1 ]; then
    info "Environment variables validated (DEEPSEEK_URL, DEEPSEEK_APIKEY present)."
fi

# ---------------------------------------------------------------------------
# Step 8: Smoke import check
# ---------------------------------------------------------------------------
info "Running smoke import check..."
python -c "import fastapi, uvicorn, sse_starlette, pydantic, dotenv, requests; print('  Imports OK')" || {
    err "Smoke import check failed. Some packages may not have installed correctly."
    exit 1
}

# ---------------------------------------------------------------------------
# Done!
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Setup complete. To start the service:"
echo ""
echo "    source .venv/bin/activate"
echo "    python3 start_service.py"
echo ""
echo "  API base URL:  http://0.0.0.0:8000"
echo ""
echo "  Route prefixes:"
echo "    /api/interview          - Interview agent"
echo "    /api/kb-organizer       - Knowledge base organizer"
echo "    /api/biography-outline  - Biography outline generation"
echo "    /api/biography-writing  - Biography writing"
echo "    /api/files              - File operations"
echo "    /health                 - Health check"
echo "============================================================"
echo ""
