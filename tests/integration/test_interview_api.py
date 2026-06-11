#!/usr/bin/env python3
"""Happy-path end-to-end test for the Interview HTTP/SSE API.

The script starts a real backend service, calls the interview flow, ends the
session, and inspects generated knowledge-base files.

Usage:
    ./.venv/bin/python tests/integration/test_interview_api.py

Optional:
    ./.venv/bin/python tests/integration/test_interview_api.py \
        --port 10080 --user-id e2e_interview_001
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

# Allow running directly from the repository root.
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
)


KB_ROOT = PROJECT_ROOT / "knowledge_base"
LOG_DIR = PROJECT_ROOT / "logs"
INTERVIEW_MESSAGES = [
    "我6到12岁是在芳草地小学读书。那时候学校离家不算近，父母每天都会叮嘱我路上注意安全。",
    "后来12到18岁，我在朝阳外国语学校读初中和高中。那段时间学习压力很大，但也认识了很多朋友。",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the service and run the interview happy-path E2E test.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Service host for the temporary backend (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Service port. Use 0 to auto-pick a free port (default: 0).",
    )
    parser.add_argument(
        "--user-id",
        default="",
        help="User id to test. Defaults to a timestamped e2e user id.",
    )
    parser.add_argument(
        "--cleanup-kb",
        action="store_true",
        help="Delete the generated e2e user knowledge base after the run.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=90.0,
        help="Seconds to wait for /health (default: 90).",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=600.0,
        help="Seconds for non-SSE requests such as /end (default: 600).",
    )
    return parser.parse_args(argv)


def pick_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def create_minimal_existing_user_kb(user_id: str) -> Path:
    """Create enough KB structure so /interview/start enters interview mode."""
    user_kb = KB_ROOT / user_id
    if user_kb.exists():
        shutil.rmtree(user_kb)

    required_directories = [
        "events/childhood",
        "events/youth",
        "events/middle_age",
        "events/elderly",
        "people/family",
        "people/friends",
        "people/colleagues",
        "people/others",
        "timeline",
        "themes",
        "sessions",
    ]
    for relative_dir in required_directories:
        (user_kb / relative_dir).mkdir(parents=True, exist_ok=True)

    (user_kb / "user.md").write_text(
        "# 被采访者档案\n\n"
        "## 基本信息\n"
        "- 微信ID: wx_e2e_interview\n"
        "- 姓名: 林建华\n"
        "- 年龄: 68\n"
        "- 性别: 男\n"
        "- 出生日期: 1958-03-12\n"
        "- 出生年份: 1958\n"
        "- 职业: 退休教师\n"
        "- 家庭状况: 已婚，有一个女儿\n"
        "- 居住情况: 上海，与妻子同住\n",
        encoding="utf-8",
    )
    (user_kb / "index.md").write_text("# 记忆库索引\n", encoding="utf-8")
    (user_kb / "summary_index.md").write_text("# 摘要索引\n", encoding="utf-8")
    (user_kb / "events" / "childhood" / "开场测试事件.md").write_text(
        "# 开场测试事件\n\n"
        "- 时间: 童年时期\n"
        "- 地点: 上海\n\n"
        "这是 E2E 测试预置事件，用于让服务识别为已有用户并进入采访阶段。\n",
        encoding="utf-8",
    )
    return user_kb


def start_service(host: str, port: int) -> tuple[subprocess.Popen[Any], Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"e2e_interview_{int(time.time())}.log"
    log_file = log_path.open("w", encoding="utf-8")
    cmd = [
        sys.executable,
        "start_service.py",
        "--host",
        host,
        "--port",
        str(port),
        "--no-reload",
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
            err(f"Backend process exited early with code {proc.returncode}")
            return False
        try:
            response = requests.get(health_url, timeout=2.0)
            if response.status_code == 200:
                info(f"Health check passed: {health_url}")
                return True
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(1.0)
    err(f"Backend did not become healthy within {timeout:.0f}s: {last_error}")
    return False


def consume_sse(
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    capture_session: bool = False,
) -> tuple[list[tuple[str, dict[str, Any]]], str | None]:
    events: list[tuple[str, dict[str, Any]]] = []
    session_id: str | None = None
    with requests.request(
        method,
        url,
        json=json_body,
        stream=True,
        timeout=(DEFAULT_TIMEOUT, SSE_READ_TIMEOUT),
        headers={"Accept": "text/event-stream"},
    ) as response:
        info(f"{method} {url} -> HTTP {response.status_code}")
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {url} failed: {response.text[:500]}")
        for event_name, data in sse_iter(response):
            events.append((event_name, data))
            print_sse_event(event_name, data)
            if capture_session and session_id is None:
                maybe_session_id = data.get("session_id")
                if isinstance(maybe_session_id, str) and maybe_session_id:
                    session_id = maybe_session_id
            if event_name == "done":
                break
    return events, session_id


def find_keyword_locations(user_kb: Path, keyword: str) -> list[Path]:
    locations: list[Path] = []
    for path in sorted((user_kb / "events").glob("*/*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if keyword in path.name or keyword in content:
            locations.append(path)
    return locations


def verify_event_classification(user_kb: Path) -> list[str]:
    failures: list[str] = []
    expectations = {
        "芳草地": "childhood",
        "朝阳外国语": "youth",
    }

    for keyword, expected_stage in expectations.items():
        locations = find_keyword_locations(user_kb, keyword)
        if not locations:
            failures.append(f"kb: no generated event file contains keyword {keyword!r}")
            continue

        pretty_locations = ", ".join(str(path.relative_to(user_kb)) for path in locations)
        info(f"keyword {keyword!r} found in: {pretty_locations}")

        if not any(path.parent.name == expected_stage for path in locations):
            failures.append(
                f"kb: expected keyword {keyword!r} under events/{expected_stage}, "
                f"got: {pretty_locations}"
            )

        elderly_locations = [path for path in locations if path.parent.name == "elderly"]
        if elderly_locations:
            failures.append(
                f"kb: keyword {keyword!r} should not be under events/elderly, got: "
                + ", ".join(str(path.relative_to(user_kb)) for path in elderly_locations)
            )

    session_files = sorted((user_kb / "sessions").glob("session_*.md"))
    if not session_files:
        failures.append(f"kb: no session archive files found under {user_kb / 'sessions'}")
    else:
        latest_session = session_files[-1]
        content = latest_session.read_text(encoding="utf-8")
        info(f"latest session archive: {latest_session}")
        if "## 结构化归档状态" not in content:
            failures.append("kb: latest session archive missing structured archive status section")
        if "- **状态**：success" not in content:
            failures.append("kb: latest session archive did not record structured archive success")

    return failures


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    port = args.port or pick_free_port(args.host)
    base_url = f"http://{args.host}:{port}"
    user_id = args.user_id or f"e2e_interview_{int(time.time())}"
    user_kb = create_minimal_existing_user_kb(user_id)
    proc: subprocess.Popen[Any] | None = None
    failures: list[str] = []

    section("Setup")
    info(f"PROJECT_ROOT = {PROJECT_ROOT}")
    info(f"BASE_URL     = {base_url}")
    info(f"USER_ID      = {user_id}")
    info(f"USER_KB      = {user_kb}")

    try:
        proc, log_path = start_service(args.host, port)
        info(f"Service log: {log_path}")
        if not wait_for_health(base_url, proc, args.startup_timeout):
            failures.append(f"service: failed to start; see log {log_path}")
            return summarize("Interview API happy path E2E", False, failures)

        section("Start Interview")
        start_events, session_id = consume_sse(
            "POST",
            f"{base_url}/api/interview/start",
            json_body={"user_id": user_id},
            capture_session=True,
        )
        if not start_events:
            failures.append("start: no SSE events received")
        if not session_id:
            failures.append("start: no session_id captured")
            return summarize("Interview API happy path E2E", False, failures)
        info(f"session_id = {session_id}")

        section("Send Messages")
        for index, message in enumerate(INTERVIEW_MESSAGES, start=1):
            info(f"message {index}: {message}")
            message_events, _ = consume_sse(
                "POST",
                f"{base_url}/api/interview/message",
                json_body={
                    "user_id": user_id,
                    "session_id": session_id,
                    "message": message,
                },
            )
            if not message_events:
                failures.append(f"message {index}: no SSE events received")

        section("Status Before End")
        status_url = f"{base_url}/api/interview/status/{user_id}/{session_id}"
        status_response = requests.get(status_url, timeout=DEFAULT_TIMEOUT)
        info(f"GET {status_url} -> HTTP {status_response.status_code}")
        info(f"body = {status_response.text[:500]}")
        if status_response.status_code != 200:
            failures.append(f"status before end: expected 200, got {status_response.status_code}")

        section("End Interview")
        end_response = requests.post(
            f"{base_url}/api/interview/end",
            json={"user_id": user_id, "session_id": session_id},
            timeout=args.request_timeout,
        )
        info(f"POST /api/interview/end -> HTTP {end_response.status_code}")
        info(f"body = {end_response.text[:1000]}")
        if end_response.status_code != 200:
            failures.append(f"end: expected 200, got {end_response.status_code}")
        else:
            body = end_response.json()
            if body.get("status") != "ended":
                failures.append(f"end: expected status='ended', got {body.get('status')!r}")
            if body.get("session_id") != session_id:
                failures.append(
                    f"end: expected session_id={session_id!r}, got {body.get('session_id')!r}"
                )
            structured_archive = body.get("structured_archive")
            if not isinstance(structured_archive, dict):
                failures.append("end: missing structured_archive object")
            elif structured_archive.get("status") != "success":
                failures.append(
                    "end: expected structured_archive.status='success', "
                    f"got {structured_archive.get('status')!r}"
                )

        section("Status After End")
        ended_status_response = requests.get(status_url, timeout=DEFAULT_TIMEOUT)
        info(f"GET {status_url} -> HTTP {ended_status_response.status_code}")
        info(f"body = {ended_status_response.text[:500]}")
        if ended_status_response.status_code != 404:
            failures.append(
                f"status after end: expected 404, got {ended_status_response.status_code}"
            )

        section("Verify Event Stage Files")
        failures.extend(verify_event_classification(user_kb))
        return summarize("Interview API happy path E2E", not failures, failures)
    except Exception as exc:
        failures.append(f"unexpected error: {exc}")
        return summarize("Interview API happy path E2E", False, failures)
    finally:
        stop_service(proc)
        if args.cleanup_kb and user_kb.exists():
            shutil.rmtree(user_kb)
            info(f"Cleaned generated KB: {user_kb}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        err("Interrupted by user")
        sys.exit(130)
