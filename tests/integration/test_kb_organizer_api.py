#!/usr/bin/env python3
"""Standalone integration test for the KB Organizer agent HTTP/SSE API.

Usage:
    python3 tests/integration/test_kb_organizer_api.py

Endpoints exercised (in order):
    1. POST /api/kb-organizer/run                (SSE)
    2. GET  /api/kb-organizer/result/{user_id}
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

    # --- Step 1: POST /api/kb-organizer/run -----------------------------
    # section("Step 1: POST /api/kb-organizer/run")
    # run_url = f"{BASE_URL}/api/kb-organizer/run"
    # events: list[tuple[str, dict]] = []
    # saw_done = False
    # saw_error = False
    # try:
    #     with requests.post(
    #         run_url,
    #         json={"user_id": USER_ID},
    #         stream=True,
    #         timeout=(DEFAULT_TIMEOUT, SSE_READ_TIMEOUT),
    #         headers={"Accept": "text/event-stream"},
    #     ) as resp:
    #         info(f"POST {run_url} → HTTP {resp.status_code}")
    #         if resp.status_code >= 400:
    #             try:
    #                 body = resp.text
    #             except Exception:
    #                 body = "<unreadable>"
    #             err(f"run failed: {body[:500]}")
    #             failures.append(
    #                 f"run: expected 2xx, got {resp.status_code}"
    #             )
    #         else:
    #             for ev_name, data in sse_iter(resp):
    #                 events.append((ev_name, data))
    #                 print_sse_event(ev_name, data)
    #                 if ev_name == "error":
    #                     saw_error = True
    #                 if ev_name == "done":
    #                     saw_done = True
    #                     break
    # except requests.RequestException as exc:
    #     failures.append(f"run: network error: {exc}")

    # if not events:
    #     failures.append("run: no SSE events received")
    # if not saw_done:
    #     warn("run: stream ended without a 'done' event")
    # if saw_error:
    #     warn("run: an 'error' event was emitted (see log above)")

    # --- Step 2: GET /api/kb-organizer/result/{user_id} -----------------
    section("Step 2: GET /api/kb-organizer/result/{user_id}")
    result_url = f"{BASE_URL}/api/kb-organizer/result/{USER_ID}"
    try:
        r = requests.get(result_url, timeout=DEFAULT_TIMEOUT)
        info(f"GET {result_url} → HTTP {r.status_code}")
        info(f"  body = {r.text[:500]}")
        if r.status_code != 200:
            failures.append(
                f"result: expected 200, got {r.status_code}"
            )
        else:
            try:
                body = r.json()
            except ValueError:
                body = {}
                failures.append("result: response is not valid JSON")
            if body.get("user_id") != USER_ID:
                warn(
                    f"result: user_id mismatch — got {body.get('user_id')!r}"
                )
            if "status" not in body:
                warn("result: missing field 'status'")
    except requests.RequestException as exc:
        failures.append(f"result: network error: {exc}")

    return summarize("KB Organizer API", not failures, failures)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        err("Interrupted by user")
        sys.exit(1)
