#!/usr/bin/env python3
"""Run all four standalone agent integration test scripts in sequence.

Usage:
    python3 tests/integration/run_all.py

Behaviour:
    - Runs each script as a subprocess, inheriting stdout/stderr so the
      user can watch live progress.
    - Captures each exit code.
    - Prints a final summary table.
    - Exits 0 only if every script exits 0.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS = [
    "test_interview_api.py",
    "test_kb_organizer_api.py",
    "test_biography_api.py",
    "test_biography_outline_api.py",
    "test_biography_writing_api.py",
]


def main() -> int:
    results: list[tuple[str, int, float]] = []

    for name in SCRIPTS:
        path = THIS_DIR / name
        print(f"\n############ Running {name} ############", flush=True)
        if not path.exists():
            print(f"[SKIP] {name} — file not found", flush=True)
            results.append((name, 127, 0.0))
            continue

        t0 = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, str(path)],
                cwd=str(THIS_DIR.parent.parent),
            )
            rc = proc.returncode
        except KeyboardInterrupt:
            print("[INTERRUPTED]", flush=True)
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] failed to run {name}: {exc}", flush=True)
            rc = 1
        elapsed = time.time() - t0
        results.append((name, rc, elapsed))

    # --- Summary table ---------------------------------------------------
    print("\n" + "=" * 72, flush=True)
    print(f"{'SCRIPT':<40s} {'RESULT':<8s} {'EXIT':>6s} {'TIME(s)':>10s}", flush=True)
    print("-" * 72, flush=True)
    overall = 0
    for name, rc, t in results:
        verdict = "PASS" if rc == 0 else "FAIL"
        if rc != 0:
            overall = 1
        print(f"{name:<40s} {verdict:<8s} {rc:>6d} {t:>10.2f}", flush=True)
    print("=" * 72, flush=True)
    print(f"OVERALL: {'PASS' if overall == 0 else 'FAIL'}", flush=True)
    return overall


if __name__ == "__main__":
    sys.exit(main())
