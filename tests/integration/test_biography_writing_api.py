#!/usr/bin/env python3
"""Standalone integration test for the Biography Writing agent HTTP/SSE API.

Usage:
    python3 tests/integration/test_biography_writing_api.py

Endpoints exercised (in order):
    1. POST /api/biography/writing/run            (SSE)
    2. GET  /api/biography/writing/{user_id}/chapters
    3. GET  /api/biography/writing/{user_id}/full

NOTE on routes: src/service/routes/biography_writing.py mounts the router
under prefix ``/biography/writing``, with ``chapters`` and ``full`` as
path-templated GETs (``/{user_id}/chapters``, ``/{user_id}/full``), not
query-string endpoints. This script honours the source-of-truth.
"""
from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from _common import (  # noqa: E402
    BASE_URL,
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

USER_ID = "test_user002_copy"


def main() -> int:
    failures: list[str] = []
    info(f"BASE_URL = {BASE_URL}")
    info(f"USER_ID  = {USER_ID}")

    # --- Step 1: POST /api/biography/writing/run -----------------------
    section("Step 1: POST /api/biography/writing/run")
    run_url = f"{BASE_URL}/api/biography/writing/run"
    events: list[tuple[str, dict]] = []
    chapter_progress_count = 0
    saw_done = False
    try:
        with requests.post(
            run_url,
            json={"user_id": USER_ID},
            stream=True,
            timeout=(DEFAULT_TIMEOUT, SSE_READ_TIMEOUT),
            headers={"Accept": "text/event-stream"},
        ) as resp:
            info(f"POST {run_url} → HTTP {resp.status_code}")
            if resp.status_code >= 400:
                try:
                    body = resp.text
                except Exception:
                    body = "<unreadable>"
                err(f"run failed: {body[:500]}")
                failures.append(
                    f"run: expected 2xx, got {resp.status_code}"
                )
            else:
                for ev_name, data in sse_iter(resp):
                    events.append((ev_name, data))
                    print_sse_event(ev_name, data)
                    # Surface per-chapter progress prominently
                    if ev_name in (
                        "chapter_started",
                        "chapter_completed",
                        "chapter_progress",
                    ):
                        chapter_progress_count += 1
                    if ev_name == "done":
                        saw_done = True
                        break
    except requests.RequestException as exc:
        failures.append(f"run: network error: {exc}")

    info(f"chapter-related events seen = {chapter_progress_count}")
    if not events:
        failures.append("run: no SSE events received")
    if not saw_done:
        warn("run: stream ended without a 'done' event")

    # --- Step 2: GET /api/biography/writing/{user_id}/chapters ---------
    section("Step 2: GET /api/biography/writing/{user_id}/chapters")
    chapters_url = f"{BASE_URL}/api/biography/writing/{USER_ID}/chapters"
    try:
        r = requests.get(chapters_url, timeout=DEFAULT_TIMEOUT)
        info(f"GET {chapters_url} → HTTP {r.status_code}")
        info(f"  body[:500] = {r.text[:500]}")
        if r.status_code != 200:
            failures.append(
                f"chapters: expected 200, got {r.status_code}"
            )
        else:
            try:
                body = r.json()
            except ValueError:
                body = {}
                failures.append("chapters: response is not valid JSON")
            if body.get("user_id") != USER_ID:
                warn(
                    f"chapters: user_id mismatch — got {body.get('user_id')!r}"
                )
            chapters = body.get("chapters")
            if not isinstance(chapters, list):
                warn("chapters: 'chapters' is not a list")
            else:
                info(f"  chapters listed = {len(chapters)}")
            if "total_word_count" not in body:
                warn("chapters: missing field 'total_word_count'")
    except requests.RequestException as exc:
        failures.append(f"chapters: network error: {exc}")

    # --- Step 3: GET /api/biography/writing/{user_id}/full -------------
    section("Step 3: GET /api/biography/writing/{user_id}/full")
    full_url = f"{BASE_URL}/api/biography/writing/{USER_ID}/full"
    try:
        r = requests.get(full_url, timeout=DEFAULT_TIMEOUT)
        info(f"GET {full_url} → HTTP {r.status_code}")
        # Don't dump full content; just preview
        info(f"  body[:300] = {r.text[:300]}")
        if r.status_code == 404:
            warn(
                "full: returned 404 — full biography not generated yet. "
                "Treating as a soft failure (may be expected on a fresh run)."
            )
        elif r.status_code != 200:
            failures.append(
                f"full: expected 200 or 404, got {r.status_code}"
            )
        else:
            try:
                body = r.json()
            except ValueError:
                body = {}
                failures.append("full: response is not valid JSON")
            for k in ("user_id", "title", "content", "total_word_count"):
                if k not in body:
                    warn(f"full: missing field '{k}'")
            content = body.get("content") or ""
            info(f"  full content length = {len(content)} chars")
    except requests.RequestException as exc:
        failures.append(f"full: network error: {exc}")

    return summarize("Biography Writing API", not failures, failures)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        err("Interrupted by user")
        sys.exit(1)
