#!/usr/bin/env python3
"""Standalone integration test for the Biography Outline agent HTTP/SSE API.

Usage:
    python3 tests/integration/test_biography_outline_api.py

Endpoints exercised (in order):
    1. POST /api/biography/outline/generate                            (SSE)
    2. GET  /api/biography/outline/{user_id}
    3. PUT  /api/biography/outline/{user_id}/chapters/{chapter_id}/confirm
       (only run if there is a chapter currently in DRAFT status)

NOTE on routes: src/service/routes/biography_outline.py declares the prefix
``/biography/outline`` (slash-separated), not ``/biography-outline`` as the
task brief mentioned. The confirm endpoint is also a path-templated PUT,
not a flat ``/confirm``. This script honours the source-of-truth.
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

    # --- Step 1: POST /api/biography/outline/generate -------------------
    section("Step 1: POST /api/biography/outline/generate")
    gen_url = f"{BASE_URL}/api/biography/outline/generate"
    events: list[tuple[str, dict]] = []
    saw_done = False
    try:
        with requests.post(
            gen_url,
            json={"user_id": USER_ID},
            stream=True,
            timeout=(DEFAULT_TIMEOUT, SSE_READ_TIMEOUT),
            headers={"Accept": "text/event-stream"},
        ) as resp:
            info(f"POST {gen_url} → HTTP {resp.status_code}")
            if resp.status_code >= 400:
                try:
                    body = resp.text
                except Exception:
                    body = "<unreadable>"
                err(f"generate failed: {body[:500]}")
                failures.append(
                    f"generate: expected 2xx, got {resp.status_code}"
                )
            else:
                for ev_name, data in sse_iter(resp):
                    events.append((ev_name, data))
                    print_sse_event(ev_name, data)
                    if ev_name == "done":
                        saw_done = True
                        break
    except requests.RequestException as exc:
        failures.append(f"generate: network error: {exc}")

    if not events:
        failures.append("generate: no SSE events received")
    if not saw_done:
        warn("generate: stream ended without a 'done' event")

    # --- Step 2: GET /api/biography/outline/{user_id} -------------------
    section("Step 2: GET /api/biography/outline/{user_id}")
    get_url = f"{BASE_URL}/api/biography/outline/{USER_ID}"
    outline: dict = {}
    try:
        r = requests.get(get_url, timeout=DEFAULT_TIMEOUT)
        info(f"GET {get_url} → HTTP {r.status_code}")
        # Truncate large outline body in log
        info(f"  body[:500] = {r.text[:500]}")
        if r.status_code != 200:
            failures.append(
                f"get outline: expected 200, got {r.status_code}"
            )
        else:
            try:
                outline = r.json()
            except ValueError:
                outline = {}
                failures.append("get outline: response is not valid JSON")
            chapters = outline.get("chapters") or []
            info(f"  chapters_count = {len(chapters)}")
            if not isinstance(chapters, list):
                warn("get outline: 'chapters' is not a list")
                chapters = []
            for k in ("title", "chapters"):
                if k not in outline:
                    warn(f"get outline: missing field '{k}'")
    except requests.RequestException as exc:
        failures.append(f"get outline: network error: {exc}")

    # --- Step 3: PUT confirm (only if a DRAFT chapter exists) ----------
    section(
        "Step 3: PUT /api/biography/outline/{user_id}/chapters/{chapter_id}/confirm"
    )
    chapters = outline.get("chapters") or []
    target_chapter = None
    for ch in chapters:
        if isinstance(ch, dict) and ch.get("status") == "draft":
            target_chapter = ch
            break

    if not target_chapter:
        info(
            "No DRAFT chapter available — skipping confirm step. "
            "(This is expected on subsequent runs.)"
        )
    else:
        chapter_id = target_chapter.get("id")
        if not isinstance(chapter_id, str) or not chapter_id:
            failures.append(
                f"confirm: target chapter has invalid id: {chapter_id!r}"
            )
        else:
            confirm_url = (
                f"{BASE_URL}/api/biography/outline/{USER_ID}"
                f"/chapters/{chapter_id}/confirm"
            )
            try:
                r = requests.put(
                    confirm_url,
                    json={"notes": "integration test confirmation"},
                    timeout=DEFAULT_TIMEOUT,
                )
                info(f"PUT {confirm_url} → HTTP {r.status_code}")
                info(f"  body = {r.text[:500]}")
                if r.status_code != 200:
                    failures.append(
                        f"confirm: expected 200, got {r.status_code}"
                    )
                else:
                    try:
                        body = r.json()
                    except ValueError:
                        body = {}
                        failures.append(
                            "confirm: response is not valid JSON"
                        )
                    if body.get("status") != "confirmed":
                        warn(
                            f"confirm: expected status='confirmed'; "
                            f"got {body.get('status')!r}"
                        )
                    if body.get("chapter_id") != chapter_id:
                        warn(
                            f"confirm: chapter_id mismatch — "
                            f"got {body.get('chapter_id')!r}"
                        )
            except requests.RequestException as exc:
                failures.append(f"confirm: network error: {exc}")

    return summarize("Biography Outline API", not failures, failures)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        err("Interrupted by user")
        sys.exit(1)
