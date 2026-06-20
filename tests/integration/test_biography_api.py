#!/usr/bin/env python3
"""End-to-end test for the Biography Generation (Track B) pipeline.

Flow under test:
    1. POST /api/biography/outline/generate       (SSE — generate outline)
    2. GET  /api/biography/outline/{user_id}       (verify outline structure)
    3. PUT  /api/biography/outline/{user_id}/chapters/{id}/confirm
       (confirm ALL draft chapters so writing can proceed)
    4. POST /api/biography/writing/run             (SSE — write chapters)
    5. GET  /api/biography/writing/{user_id}/chapters  (verify chapter files)
    6. GET  /api/biography/writing/{user_id}/full      (verify merged biography)

Usage:
    ./.venv/bin/python tests/integration/test_biography_api.py

Optional:
    ./.venv/bin/python tests/integration/test_biography_api.py \
        --port 10080 --source-user-id user_1780406830166
"""
from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from _common import (  # noqa: E402
    DEFAULT_TIMEOUT,
    SSE_READ_TIMEOUT,
    err,
    info,
    print_sse_event,
    requests,
    section,
    sse_iter,
    summarize,
    warn,
)

KB_ROOT = PROJECT_ROOT / "knowledge_base"
LOG_DIR = PROJECT_ROOT / "logs"
SOURCE_USER_ID = "user_1780406830166"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Biography generation (Track B) end-to-end test.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0,
                        help="0 = auto-pick a free port")
    parser.add_argument("--source-user-id", default=SOURCE_USER_ID,
                        help="Existing user whose KB events/people to copy.")
    parser.add_argument("--cleanup-kb", action="store_true",
                        help="Delete the generated test KB after the run.")
    parser.add_argument("--startup-timeout", type=float, default=90.0)
    parser.add_argument("--request-timeout", type=float, default=900.0,
                        help="Timeout for long-running SSE endpoints.")
    return parser.parse_args(argv)


def pick_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


# ---------------------------------------------------------------------------
# KB setup
# ---------------------------------------------------------------------------

def create_test_kb(source_user_id: str, test_user_id: str) -> Path:
    """Copy events/people/timeline from source user to a fresh test user KB.

    The biography/ directory is intentionally NOT copied so the test starts
    from scratch and exercises the full outline → write pipeline.
    """
    source_kb = KB_ROOT / source_user_id
    if not source_kb.exists():
        raise RuntimeError(f"Source KB not found: {source_kb}")

    test_kb = KB_ROOT / test_user_id
    if test_kb.exists():
        shutil.rmtree(test_kb)
    test_kb.mkdir(parents=True)

    # Copy the directories the outline agent scans.
    for subdir in ("events", "people", "timeline", "themes", "sessions"):
        src = source_kb / subdir
        if src.exists():
            shutil.copytree(src, test_kb / subdir)

    # Copy metadata files needed for outline generation.
    for filename in ("user.md", "index.md", "summary_index.md"):
        src = source_kb / filename
        if src.exists():
            shutil.copy2(src, test_kb / filename)

    # Ensure biography/ exists but is empty (the agent will create outline.yaml).
    (test_kb / "biography" / "chapters").mkdir(parents=True, exist_ok=True)

    info(f"Copied KB from {source_user_id!r} → {test_kb}")
    return test_kb


# ---------------------------------------------------------------------------
# Service lifecycle
# ---------------------------------------------------------------------------

def start_service(host: str, port: int) -> tuple[subprocess.Popen[Any], Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"e2e_biography_{int(time.time())}.log"
    log_file = log_path.open("w", encoding="utf-8")
    cmd = [
        sys.executable, "start_service.py",
        "--host", host, "--port", str(port), "--no-reload",
    ]
    info("Starting backend service: " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    proc._e2e_log_file = log_file  # type: ignore[attr-defined]
    return proc, log_path


def stop_service(proc: subprocess.Popen[Any] | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    log_file = getattr(proc, "_e2e_log_file", None)
    if log_file is not None:
        log_file.close()


def wait_for_health(base_url: str, proc: subprocess.Popen[Any], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    health_url = f"{base_url}/health"
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            err(f"Backend exited early with code {proc.returncode}")
            return False
        try:
            r = requests.get(health_url, timeout=2.0)
            if r.status_code == 200:
                info(f"Health check passed: {health_url}")
                return True
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(1.0)
    err(f"Backend not healthy within {timeout:.0f}s: {last_error}")
    return False


# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------

def consume_sse(
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    request_timeout: float = 900.0,
) -> list[tuple[str, dict[str, Any]]]:
    """Consume an SSE stream and return all events."""
    events: list[tuple[str, dict[str, Any]]] = []
    with requests.request(
        method,
        url,
        json=json_body,
        stream=True,
        timeout=(DEFAULT_TIMEOUT, SSE_READ_TIMEOUT),
        headers={"Accept": "text/event-stream"},
    ) as resp:
        info(f"{method} {url} → HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise RuntimeError(f"{method} {url} failed: {resp.text[:500]}")
        for ev_name, data in sse_iter(resp):
            events.append((ev_name, data))
            print_sse_event(ev_name, data)
            if ev_name == "done":
                break
    return events


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    port = args.port or pick_free_port(args.host)
    base_url = f"http://{args.host}:{port}"
    source_user_id = args.source_user_id
    test_user_id = f"e2e_biography_{int(time.time())}"

    proc: subprocess.Popen[Any] | None = None
    test_kb: Path | None = None
    failures: list[str] = []

    section("Setup")
    info(f"PROJECT_ROOT    = {PROJECT_ROOT}")
    info(f"BASE_URL        = {base_url}")
    info(f"SOURCE_USER_ID  = {source_user_id}")
    info(f"TEST_USER_ID    = {test_user_id}")

    try:
        # ---- Setup -------------------------------------------------------
        test_kb = create_test_kb(source_user_id, test_user_id)
        proc, log_path = start_service(args.host, port)
        info(f"Service log: {log_path}")
        if not wait_for_health(base_url, proc, args.startup_timeout):
            failures.append(f"service: failed to start; see {log_path}")
            return summarize("Biography Track B E2E", False, failures)

        # ---- Step 1: Generate Outline ------------------------------------
        section("Step 1: POST /api/biography/outline/generate")
        outline_events = consume_sse(
            "POST",
            f"{base_url}/api/biography/outline/generate",
            json_body={"user_id": test_user_id},
            request_timeout=args.request_timeout,
        )
        if not outline_events:
            failures.append("outline generate: no SSE events received")
        completed_events = [e for e in outline_events if e[0] == "completed"]
        if not completed_events:
            warn("outline generate: no 'completed' event seen (may still have succeeded)")

        # ---- Step 2: GET outline -----------------------------------------
        section("Step 2: GET /api/biography/outline/{user_id}")
        outline_url = f"{base_url}/api/biography/outline/{test_user_id}"
        outline: dict = {}
        try:
            r = requests.get(outline_url, timeout=DEFAULT_TIMEOUT)
            info(f"GET {outline_url} → HTTP {r.status_code}")
            if r.status_code != 200:
                failures.append(f"get outline: expected 200, got {r.status_code}")
            else:
                outline = r.json()
                chapters = outline.get("chapters") or []
                info(f"outline title  = {outline.get('title')!r}")
                info(f"outline author = {outline.get('author')!r}")
                info(f"chapters_count = {len(chapters)}")

                if not chapters:
                    failures.append("get outline: chapters list is empty")

                # Verify each chapter has required fields
                for ch in chapters[:3]:  # spot-check first 3
                    for field in ("id", "title", "life_stage", "status"):
                        if field not in ch:
                            failures.append(f"get outline: chapter missing field {field!r}: {ch!r}")
        except requests.RequestException as exc:
            failures.append(f"get outline: network error: {exc}")

        # ---- Step 3: Confirm all draft chapters --------------------------
        section("Step 3: PUT confirm all draft chapters")
        chapters = outline.get("chapters") or []
        draft_chapters = [
            ch for ch in chapters
            if isinstance(ch, dict) and ch.get("status") == "draft"
        ]
        confirmed_count = 0
        already_confirmed = [
            ch for ch in chapters
            if isinstance(ch, dict) and ch.get("status") != "draft"
        ]
        info(f"draft chapters to confirm: {len(draft_chapters)}")
        info(f"already non-draft: {len(already_confirmed)}")

        for ch in draft_chapters:
            chapter_id = ch.get("id")
            if not chapter_id:
                failures.append(f"confirm: chapter has no id: {ch!r}")
                continue
            confirm_url = (
                f"{base_url}/api/biography/outline/{test_user_id}"
                f"/chapters/{chapter_id}/confirm"
            )
            try:
                r = requests.put(
                    confirm_url,
                    json={"notes": "e2e test auto-confirm"},
                    timeout=DEFAULT_TIMEOUT,
                )
                if r.status_code == 200:
                    body = r.json()
                    if body.get("status") == "confirmed":
                        confirmed_count += 1
                        info(f"  confirmed: {chapter_id} ({ch.get('title', '')!r})")
                    else:
                        failures.append(
                            f"confirm {chapter_id}: expected status='confirmed', "
                            f"got {body.get('status')!r}"
                        )
                else:
                    failures.append(
                        f"confirm {chapter_id}: expected 200, got {r.status_code}: {r.text[:200]}"
                    )
            except requests.RequestException as exc:
                failures.append(f"confirm {chapter_id}: network error: {exc}")

        total_confirmed = confirmed_count + len(already_confirmed)
        info(f"total confirmed (or non-draft): {total_confirmed} / {len(chapters)}")

        if not draft_chapters and not already_confirmed:
            failures.append("confirm: no chapters available to confirm or write")

        # ---- Step 4: Run Writing -----------------------------------------
        section("Step 4: POST /api/biography/writing/run")
        writing_events = consume_sse(
            "POST",
            f"{base_url}/api/biography/writing/run",
            json_body={"user_id": test_user_id},
            request_timeout=args.request_timeout,
        )
        if not writing_events:
            failures.append("writing: no SSE events received")
        writing_completed = [e for e in writing_events if e[0] == "completed"]
        if not writing_completed:
            warn("writing: no 'completed' event (may still have succeeded)")

        # ---- Step 5: GET chapters ----------------------------------------
        section("Step 5: GET /api/biography/writing/{user_id}/chapters")
        chapters_url = f"{base_url}/api/biography/writing/{test_user_id}/chapters"
        try:
            r = requests.get(chapters_url, timeout=DEFAULT_TIMEOUT)
            info(f"GET {chapters_url} → HTTP {r.status_code}")
            if r.status_code != 200:
                failures.append(f"get chapters: expected 200, got {r.status_code}")
            else:
                body = r.json()
                written_chapters = body.get("chapters") or []
                total_words = body.get("total_word_count", 0)
                info(f"written chapters: {len(written_chapters)}")
                info(f"total_word_count: {total_words}")

                if not written_chapters:
                    failures.append("get chapters: no chapter files found")

                for wc in written_chapters:
                    info(f"  [{wc.get('chapter_id')}] {wc.get('title')!r} "
                         f"({wc.get('word_count', 0)} bytes)")
        except requests.RequestException as exc:
            failures.append(f"get chapters: network error: {exc}")

        # ---- Step 6: GET full biography ----------------------------------
        section("Step 6: GET /api/biography/writing/{user_id}/full")
        full_url = f"{base_url}/api/biography/writing/{test_user_id}/full"
        try:
            r = requests.get(full_url, timeout=DEFAULT_TIMEOUT)
            info(f"GET {full_url} → HTTP {r.status_code}")
            if r.status_code != 200:
                failures.append(f"get full: expected 200, got {r.status_code}")
            else:
                body = r.json()
                title = body.get("title", "")
                total_wc = body.get("total_word_count", 0)
                chapters_count = body.get("chapters_count", 0)
                content = body.get("content", "")
                info(f"full title         = {title!r}")
                info(f"full chapters_count = {chapters_count}")
                info(f"full word_count    = {total_wc}")
                info(f"content preview    = {content[:200]!r}...")

                if not content.strip():
                    failures.append("get full: content is empty")
                if total_wc == 0:
                    failures.append("get full: total_word_count is 0")
        except requests.RequestException as exc:
            failures.append(f"get full: network error: {exc}")

        # ---- Verify output files -----------------------------------------
        section("Verify Output Files")
        if test_kb is not None:
            outline_path = test_kb / "biography" / "outline.yaml"
            full_bio_path = test_kb / "biography" / "full_biography.md"
            chapters_dir = test_kb / "biography" / "chapters"

            if not outline_path.exists():
                failures.append("files: outline.yaml not found")
            else:
                info(f"outline.yaml: {outline_path.stat().st_size} bytes")

            if not full_bio_path.exists():
                failures.append("files: full_biography.md not found")
            else:
                size = full_bio_path.stat().st_size
                info(f"full_biography.md: {size} bytes")

            if chapters_dir.exists():
                chapter_files = list(chapters_dir.glob("*.md"))
                info(f"chapter files: {len(chapter_files)}")
                for cf in sorted(chapter_files):
                    info(f"  {cf.name}: {cf.stat().st_size} bytes")
            else:
                failures.append("files: biography/chapters/ directory not found")

        return summarize("Biography Track B E2E", not failures, failures)

    except Exception as exc:
        failures.append(f"unexpected error: {exc}")
        return summarize("Biography Track B E2E", False, failures)
    finally:
        stop_service(proc)
        if args.cleanup_kb and test_kb is not None and test_kb.exists():
            shutil.rmtree(test_kb)
            info(f"Cleaned test KB: {test_kb}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        err("Interrupted by user")
        sys.exit(130)
