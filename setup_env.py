#!/usr/bin/env python3
"""setup_env.py - Cross-platform one-click setup for the Agent Service.

A Python equivalent of setup.sh for Windows/CI compatibility.
Uses only the standard library.

Usage:
    python setup_env.py [--dev] [--verbose] [--no-venv] [--help]
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
REQ_FILE = PROJECT_ROOT / "requirements.txt"
REQ_DEV_FILE = PROJECT_ROOT / "requirements-dev.txt"
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
MIN_PYTHON = (3, 9)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def info(msg: str) -> None:
    print(f"[setup] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[setup] WARNING: {msg}", file=sys.stderr, flush=True)


def err(msg: str) -> None:
    print(f"[setup] ERROR: {msg}", file=sys.stderr, flush=True)


def banner() -> None:
    print()
    print("=" * 60)
    print("  Elder Memoir Agent Service - Cloud Setup")
    print("=" * 60)
    print()


def run(cmd: list[str], *, quiet: bool = False, check: bool = True) -> None:
    """Run a subprocess command with optional quiet mode."""
    kwargs: dict = {"check": check}
    if quiet:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    subprocess.run(cmd, **kwargs)


def find_python() -> str:
    """Find a suitable Python interpreter (>= MIN_PYTHON)."""
    # On Windows, python3 may not exist; try python first if it's 3.x
    candidates = ["python3.11", "python3.10", "python3"]
    if platform.system() == "Windows":
        candidates = ["python3.11", "python3.10", "python3", "python"]

    for candidate in candidates:
        path = shutil.which(candidate)
        if path is None:
            continue
        try:
            result = subprocess.run(
                [path, "-c", "import sys; print(sys.version_info.major, sys.version_info.minor)"],
                capture_output=True,
                text=True,
                check=True,
            )
            major, minor = map(int, result.stdout.strip().split())
            if (major, minor) >= MIN_PYTHON:
                return path
        except (subprocess.CalledProcessError, ValueError):
            continue

    return ""


def get_venv_python() -> str:
    """Return the path to the venv Python interpreter."""
    if platform.system() == "Windows":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def get_venv_pip() -> str:
    """Return the path to the venv pip."""
    if platform.system() == "Windows":
        return str(VENV_DIR / "Scripts" / "pip.exe")
    return str(VENV_DIR / "bin" / "pip")


def check_env_var(name: str) -> bool:
    """Check that a variable is present and non-placeholder in .env."""
    if not ENV_FILE.exists():
        return False
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == name:
            val = value.strip()
            if val and val != "your_api_key_here":
                return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-click setup for the Agent Service (cross-platform).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
This script is idempotent — safe to re-run at any time.

Examples:
  python setup_env.py              # Standard setup
  python setup_env.py --dev        # Include dev/test dependencies
  python setup_env.py --no-venv    # Skip venv (Docker, CI)
""",
    )
    parser.add_argument("--dev", action="store_true", help="Also install dev dependencies")
    parser.add_argument("--verbose", action="store_true", help="Show pip output")
    parser.add_argument("--no-venv", action="store_true", help="Skip venv creation/activation")
    args = parser.parse_args()

    banner()

    # ------------------------------------------------------------------
    # Step 1: Detect Python
    # ------------------------------------------------------------------
    info("Detecting Python interpreter...")
    python_path = find_python()
    if not python_path:
        err(f"No suitable Python found (need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}).")
        err("Please install Python 3.10+ and ensure it is on PATH.")
        return 1

    result = subprocess.run(
        [python_path, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        capture_output=True, text=True, check=True,
    )
    py_version = result.stdout.strip()
    info(f"Using {python_path} (version {py_version})")

    # ------------------------------------------------------------------
    # Step 2: Detect / bootstrap pip
    # ------------------------------------------------------------------
    try:
        subprocess.run(
            [python_path, "-m", "pip", "--version"],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError:
        info("pip not found — bootstrapping via ensurepip...")
        try:
            subprocess.run([python_path, "-m", "ensurepip", "--default-pip"], check=True)
        except subprocess.CalledProcessError:
            err("Could not install pip. Please install pip manually.")
            return 1

    # ------------------------------------------------------------------
    # Step 3: Create / activate venv
    # ------------------------------------------------------------------
    pip_cmd: str
    python_cmd: str

    if not args.no_venv:
        if not VENV_DIR.exists():
            info(f"Creating virtual environment at {VENV_DIR} ...")
            subprocess.run([python_path, "-m", "venv", str(VENV_DIR)], check=True)
        else:
            info(f"Reusing existing virtual environment at {VENV_DIR}")

        python_cmd = get_venv_python()
        pip_cmd = get_venv_pip()
        info("Virtual environment ready.")
    else:
        info("Skipping venv (--no-venv).")
        python_cmd = python_path
        pip_cmd = f"{python_path} -m pip"  # fallback; we'll use list form below

    # Build pip command as list
    if args.no_venv:
        pip_base = [python_path, "-m", "pip"]
    else:
        pip_base = [pip_cmd]

    quiet_flag = [] if args.verbose else ["--quiet"]

    # ------------------------------------------------------------------
    # Step 4: Upgrade pip + build tools
    # ------------------------------------------------------------------
    info("Upgrading pip, setuptools, wheel...")
    run(pip_base + ["install", "--upgrade", "pip", "setuptools", "wheel"] + quiet_flag)

    # ------------------------------------------------------------------
    # Step 5: Install requirements
    # ------------------------------------------------------------------
    info(f"Installing production dependencies from {REQ_FILE.name}...")
    run(pip_base + ["install", "-r", str(REQ_FILE)] + quiet_flag)

    if args.dev:
        info(f"Installing dev dependencies from {REQ_DEV_FILE.name}...")
        run(pip_base + ["install", "-r", str(REQ_DEV_FILE)] + quiet_flag)

    # ------------------------------------------------------------------
    # Step 6: .env handling
    # ------------------------------------------------------------------
    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            info(f"Copying {ENV_EXAMPLE.name} -> {ENV_FILE.name}")
            shutil.copy2(ENV_EXAMPLE, ENV_FILE)
            warn("Created .env from .env.example — you MUST fill in DEEPSEEK_URL and DEEPSEEK_APIKEY.")
        else:
            err(f"Neither {ENV_FILE.name} nor {ENV_EXAMPLE.name} found.")
            err("Please create a .env file with DEEPSEEK_URL and DEEPSEEK_APIKEY.")
            return 1
    else:
        info(".env file already exists — not overwriting.")

    # ------------------------------------------------------------------
    # Step 7: Validate environment variables (warn, do not fail)
    # ------------------------------------------------------------------
    env_ok = True
    for var in ("DEEPSEEK_URL", "DEEPSEEK_APIKEY"):
        if not check_env_var(var):
            warn(f"{var} is missing or has a placeholder value in .env")
            warn("  (Cloud deployments may inject env vars at runtime — this is not fatal.)")
            env_ok = False
    if env_ok:
        info("Environment variables validated (DEEPSEEK_URL, DEEPSEEK_APIKEY present).")

    # ------------------------------------------------------------------
    # Step 8: Smoke import check
    # ------------------------------------------------------------------
    info("Running smoke import check...")
    smoke_code = "import fastapi, uvicorn, sse_starlette, pydantic, dotenv, requests; print('  Imports OK')"
    try:
        subprocess.run([python_cmd, "-c", smoke_code], check=True)
    except subprocess.CalledProcessError:
        err("Smoke import check failed. Some packages may not have installed correctly.")
        return 1

    # ------------------------------------------------------------------
    # Done!
    # ------------------------------------------------------------------
    activate_cmd = (
        r"  .venv\Scripts\activate" if platform.system() == "Windows"
        else "  source .venv/bin/activate"
    )
    print()
    print("=" * 60)
    print("  Setup complete. To start the service:")
    print()
    print(activate_cmd)
    print("    python3 start_service.py")
    print()
    print("  API base URL:  http://0.0.0.0:8000")
    print()
    print("  Route prefixes:")
    print("    /api/interview          - Interview agent")
    print("    /api/kb-organizer       - Knowledge base organizer")
    print("    /api/biography-outline  - Biography outline generation")
    print("    /api/biography-writing  - Biography writing")
    print("    /api/files              - File operations")
    print("    /health                 - Health check")
    print("=" * 60)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
