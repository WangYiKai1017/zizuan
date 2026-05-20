#!/usr/bin/env python3
"""start_service.py - Cross-platform launcher for the Agent Service backend.

Usage:
    python3 start_service.py [--host HOST] [--port PORT]
                             [--reload | --no-reload]
                             [--install] [--check-only]

This script:
  * Loads environment variables from `.env` at the project root.
  * Validates that DEEPSEEK_URL and DEEPSEEK_APIKEY are set.
  * Optionally installs dependencies from requirements.txt.
  * Prints a startup banner listing the available API route prefixes.
  * Launches uvicorn programmatically against `run_server:app`.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"

REQUIRED_ENV_VARS = ("DEEPSEEK_URL", "DEEPSEEK_APIKEY")

API_ROUTES = [
    ("/api/interview", "start, message, end, status"),
    ("/api/kb-organizer", "run, result"),
    ("/api/biography-outline", "generate, get, confirm"),
    ("/api/biography-writing", "run, chapters, full"),
    ("/api/files", "list, tree, content"),
]


def _log(msg: str) -> None:
    print(f"[start_service] {msg}")


def _err(msg: str) -> None:
    print(f"[start_service] ERROR: {msg}", file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the Agent Service backend (FastAPI / uvicorn).",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")

    reload_group = parser.add_mutually_exclusive_group()
    reload_group.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        help="Enable uvicorn auto-reload (default).",
    )
    reload_group.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="Disable uvicorn auto-reload (recommended for integration tests).",
    )
    parser.set_defaults(reload=True)

    parser.add_argument(
        "--install",
        action="store_true",
        help="Run 'pip install -r requirements.txt' before starting.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run env / dependency checks and exit without starting the server.",
    )
    return parser.parse_args(argv)


def load_dotenv_file() -> bool:
    """Load `.env` using python-dotenv if available, else a minimal fallback."""
    if not ENV_FILE.exists():
        _err(f".env file not found at {ENV_FILE}")
        _err("Copy .env.example to .env and fill in DEEPSEEK_URL and DEEPSEEK_APIKEY.")
        return False

    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(ENV_FILE, override=False)
        return True
    except ImportError:
        # Minimal fallback parser - good enough for KEY=VALUE lines.
        _log("python-dotenv not installed; using minimal fallback parser.")
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return True


def check_required_env() -> bool:
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        for name in missing:
            _err(f"Required environment variable '{name}' is missing or empty in .env")
        return False
    _log("Environment check passed (DEEPSEEK_URL and DEEPSEEK_APIKEY are set).")
    return True


def install_dependencies() -> bool:
    if not REQUIREMENTS_FILE.exists():
        _err(f"requirements.txt not found at {REQUIREMENTS_FILE}")
        return False
    _log("Installing dependencies from requirements.txt ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
        check=False,
    )
    if result.returncode != 0:
        _err("pip install failed.")
        return False
    return True


def print_banner(host: str, port: int, reload: bool) -> None:
    line = "=" * 60
    sep = "-" * 60
    print()
    print(line)
    print("  Agent Service - starting up")
    print(sep)
    print(f"  URL          : http://{host}:{port}")
    print(f"  Reload       : {'enabled' if reload else 'disabled'}")
    print(f"  Project root : {PROJECT_ROOT}")
    print()
    print("  Available API route prefixes:")
    for prefix, ops in API_ROUTES:
        print(f"    - {prefix:<24s} ({ops})")
    print(line)
    print()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Always run from project root so uvicorn can import run_server:app.
    os.chdir(PROJECT_ROOT)

    if not load_dotenv_file():
        return 1

    if not check_required_env():
        return 1

    if args.install:
        if not install_dependencies():
            return 1

    if args.check_only:
        _log("Check-only mode: all checks passed. Exiting without starting the server.")
        return 0

    try:
        import uvicorn  # type: ignore
    except ImportError:
        _err("uvicorn is not installed. Run with --install or 'pip install -r requirements.txt'.")
        return 1

    print_banner(args.host, args.port, args.reload)

    uvicorn.run(
        "run_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
