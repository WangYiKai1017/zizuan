#!/usr/bin/env python3
"""Standalone integration test for the Interview agent HTTP/SSE API.

Usage:
    python3 tests/integration/test_interview_api.py

Endpoints exercised (in order):
    1. POST /api/interview/start                  (SSE)
    2. POST /api/interview/message                (SSE)
    3. GET  /api/interview/status/{user_id}/{session_id}
    4. POST /api/interview/end                    (JSON)
    5. GET  /api/interview/status/{user_id}/{session_id}  (expects 404)

NOTE on routes: the actual route in src/service/routes/interview.py declares
``GET /status/{user_id}/{session_id}`` (path params), not the
``GET /status?user_id=...`` query-param form mentioned in the task description.
This script honours the source-of-truth implementation.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running directly: `python3 tests/integration/test_interview_api.py`
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

USER_ID = "test_user_interview"


def _consume_sse(
    method: str,
    url: str,
    *,
    json_body: dict | None = None,
    capture_session: bool = False,
) -> tuple[list[tuple[str, dict]], str | None]:
    """POST + consume an SSE stream. Print events live; return events + session_id."""
    events: list[tuple[str, dict]] = []
    session_id: str | None = None
    try:
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
                # Non-streaming error body
                try:
                    body = resp.text
                except Exception:
                    body = "<unreadable>"
                err(f"Request failed: {body[:500]}")
                return events, None
            for ev_name, data in sse_iter(resp):
                events.append((ev_name, data))
                print_sse_event(ev_name, data)
                if capture_session and session_id is None:
                    sid = data.get("session_id")
                    if isinstance(sid, str) and sid:
                        session_id = sid
                if ev_name == "done":
                    break
                if ev_name == "error":
                    # Keep consuming until done arrives, but log it
                    pass
    except requests.RequestException as exc:
        err(f"Network/HTTP error during SSE consumption: {exc}")
    return events, session_id


def main() -> int:
    failures: list[str] = []
    info(f"BASE_URL = {BASE_URL}")
    info(f"USER_ID  = {USER_ID}")

    # --- Step 1: POST /api/interview/start ------------------------------
    section("Step 1: POST /api/interview/start")
    start_url = f"{BASE_URL}/api/interview/start"
    start_events, session_id = _consume_sse(
        "POST", start_url, json_body={"user_id": USER_ID}, capture_session=True
    )
    if not start_events:
        failures.append("start: no SSE events received")
    if not session_id:
        failures.append("start: no session_id captured from SSE events")
        # Hard-fail downstream steps if we have no session_id
        return summarize("Interview API", False, failures)
    if not isinstance(session_id, str) or not session_id.strip():
        failures.append(f"start: invalid session_id {session_id!r}")

    # Validate at least one of the expected event names appeared
    start_event_names = {e for e, _ in start_events}
    expected_any = {"session_started", "agent_message", "done"}
    if not (start_event_names & expected_any):
        warn(
            f"start: did not see any of {expected_any}; "
            f"got {sorted(start_event_names)}"
        )

    info(f"Captured session_id = {session_id}")

    # --- Step 2a: POST /api/interview/message (backward compat) ---------
    section("Step 2a: POST /api/interview/message (backward compat)")
    msg_url = f"{BASE_URL}/api/interview/message"
    msg_payload_compat = {
        "user_id": USER_ID,
        "session_id": session_id,
        "message": "你好，我想开始讲我的故事",
    }
    msg_events_compat, _ = _consume_sse("POST", msg_url, json_body=msg_payload_compat)
    if not msg_events_compat:
        failures.append("message_compat: no SSE events received")
    msg_event_names_compat = {e for e, _ in msg_events_compat}
    if "agent_message" not in msg_event_names_compat and "error" not in msg_event_names_compat:
        warn(
            f"message_compat: expected 'agent_message' (or 'error'); "
            f"got {sorted(msg_event_names_compat)}"
        )

    # Validate new fields are present in backward-compat mode
    for ev_name, data in msg_events_compat:
        if ev_name == "agent_message":
            if "question_source" not in data:
                failures.append("message_compat: missing 'question_source' in agent_message")
            if "candidate_question_id" not in data:
                failures.append("message_compat: missing 'candidate_question_id' in agent_message")

    # --- Step 2b: POST /api/interview/message (with candidate_questions) --
    # Use a message highly relevant to one candidate question so LLM is likely to select it.
    section("Step 2b: POST /api/interview/message (with candidate_questions)")
    msg_payload_cq = {
        "user_id": USER_ID,
        "session_id": session_id,
        "message": "我年轻时在部队待了五年，那时候条件很苦，但从来没后悔过。",
        "candidate_questions": [
            {"id": "q_army", "question": "您当年为什么选择参军？"},
            {"id": "q_friend", "question": "部队里最难忘的人是谁？"},
        ],
    }
    msg_events_cq, _ = _consume_sse("POST", msg_url, json_body=msg_payload_cq)
    if not msg_events_cq:
        failures.append("message_cq: no SSE events received")
    msg_event_names_cq = {e for e, _ in msg_events_cq}
    if "agent_message" not in msg_event_names_cq and "error" not in msg_event_names_cq:
        warn(
            f"message_cq: expected 'agent_message' (or 'error'); "
            f"got {sorted(msg_event_names_cq)}"
        )

    # Validate new fields are present when candidate_questions are sent
    cq_source = None
    cq_id = None
    for ev_name, data in msg_events_cq:
        if ev_name == "agent_message":
            if "question_source" not in data:
                failures.append("message_cq: missing 'question_source' in agent_message")
            if "candidate_question_id" not in data:
                failures.append("message_cq: missing 'candidate_question_id' in agent_message")
            cq_source = data.get("question_source")
            cq_id = data.get("candidate_question_id")
            info(
                f"message_cq: question_source={cq_source!r}, "
                f"candidate_question_id={cq_id!r}"
            )

    # Log whether a candidate question was consumed (best-effort with real LLM)
    if cq_source == "candidate_question" and cq_id:
        info(f"SUCCESS: LLM selected candidate question {cq_id!r}")
    else:
        warn(
            "LLM did not select a candidate question this run (non-deterministic with real LLM). "
            "This is acceptable for integration tests."
        )

    # --- Step 3: GET /api/interview/status/{user_id}/{session_id} -------
    section("Step 3: GET /api/interview/status/{user_id}/{session_id}")
    status_url = f"{BASE_URL}/api/interview/status/{USER_ID}/{session_id}"
    try:
        r = requests.get(status_url, timeout=DEFAULT_TIMEOUT)
        info(f"GET {status_url} → HTTP {r.status_code}")
        info(f"  body = {r.text[:500]}")
        if r.status_code != 200:
            failures.append(
                f"status (active): expected 200, got {r.status_code}"
            )
        else:
            try:
                body = r.json()
            except ValueError:
                body = {}
                failures.append("status (active): response is not valid JSON")
            if body.get("session_id") != session_id:
                warn(
                    f"status (active): session_id mismatch — "
                    f"got {body.get('session_id')!r}, expected {session_id!r}"
                )
            for k in ("session_id", "user_id", "phase"):
                if k not in body:
                    warn(f"status (active): missing field '{k}'")
    except requests.RequestException as exc:
        failures.append(f"status (active): network error: {exc}")

    # --- Step 4: POST /api/interview/end --------------------------------
    section("Step 4: POST /api/interview/end")
    end_url = f"{BASE_URL}/api/interview/end"
    end_payload = {"user_id": USER_ID, "session_id": session_id}
    try:
        r = requests.post(end_url, json=end_payload, timeout=DEFAULT_TIMEOUT)
        info(f"POST {end_url} → HTTP {r.status_code}")
        info(f"  body = {r.text[:500]}")
        if r.status_code != 200:
            failures.append(f"end: expected 200, got {r.status_code}")
        else:
            try:
                body = r.json()
            except ValueError:
                body = {}
                failures.append("end: response is not valid JSON")
            if body.get("status") != "ended":
                warn(f"end: expected status='ended'; got {body.get('status')!r}")
            if body.get("session_id") != session_id:
                warn(
                    f"end: session_id mismatch — "
                    f"got {body.get('session_id')!r}, expected {session_id!r}"
                )
    except requests.RequestException as exc:
        failures.append(f"end: network error: {exc}")

    # --- Step 5: status after end → expect 404 --------------------------
    section("Step 5: GET /api/interview/status (after end → 404)")
    try:
        r = requests.get(status_url, timeout=DEFAULT_TIMEOUT)
        info(f"GET {status_url} → HTTP {r.status_code}")
        info(f"  body = {r.text[:500]}")
        if r.status_code != 404:
            failures.append(
                f"status (after end): expected 404, got {r.status_code}"
            )
    except requests.RequestException as exc:
        failures.append(f"status (after end): network error: {exc}")

    return summarize("Interview API", not failures, failures)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        err("Interrupted by user")
        sys.exit(1)
