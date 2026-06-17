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
import json
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
    # 第三轮：答非所问——上文应该还在追问学校/朋友相关，用户突然聊到邻居
    "说起那时候，我最怀念的其实是我家隔壁的李奶奶。她家院子里有棵大枣树，"
    "每年秋天都叫我去打枣。她一个人住，儿子在外地工作，我放学了就爱往她家跑。",
    # 第四轮：提供丰富细节（时间/地点/人物/感受），测试叙事完整性信号
    "初三那年，教语文的王老师特别鼓励我。有一次我写了一篇作文叫《院子里的四季》，"
    "她拿到全班念了一遍，还推荐我去参加区里的作文比赛。我居然拿了个一等奖，"
    "当时特别激动，觉得有人认可我了。",
    # 第五轮：简短回答 + 情感反思，测试情绪饱和度与隐性诉求信号
    "嗯，后来选大学专业的时候我就选了中文系。王老师对我的影响挺大的，"
    "现在回想起来，要是没有她那句鼓励，我可能走的是另一条路了。",
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


def read_guided_state(user_kb: Path) -> dict:
    """Read the guided_initial_state.json file."""
    state_file = user_kb / "guided_initial_state.json"
    if not state_file.exists():
        return {}
    try:
        raw = state_file.read_text(encoding="utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def verify_guided_state(user_kb: Path) -> list[str]:
    """Verify guided state reflects independent completion/transition logic."""
    failures: list[str] = []
    state = read_guided_state(user_kb)
    if not state:
        failures.append("guided_state: file missing or unreadable")
        return failures

    info(f"guided_state = {json.dumps(state, ensure_ascii=False)}")

    # With only 5 messages, guided phase should NOT be completed (64 preset questions)
    if state.get("guided_completed") is True:
        failures.append("guided_state: guided_completed should be false after only 5 messages")

    completed_ids = state.get("completed_question_ids", [])
    info(f"completed_question_ids = {completed_ids}")

    # At most a few questions should be completed after 5 messages.
    # If many are completed, the LLM is likely marking questions done without proper justification.
    if len(completed_ids) > 3:
        failures.append(
            f"guided_state: {len(completed_ids)} questions completed after only 5 messages, "
            "expected at most 3 (LLM may be over-marking completions)"
        )

    # current_question_id should be valid and not in completed list
    current_id = state.get("current_question_id")
    if current_id and current_id in completed_ids:
        failures.append(
            f"guided_state: current_question_id {current_id!r} is in completed_question_ids"
        )

    return failures


def inject_fake_events(user_kb: Path, life_stage: str, count: int) -> list[Path]:
    """Inject count fake event files into events/{life_stage}/ for story generation testing."""
    events_dir = user_kb / "events" / life_stage
    events_dir.mkdir(parents=True, exist_ok=True)

    templates = [
        ("小时候在弄堂里玩弹珠", "1963年夏天", "childhood", "other"),
        ("第一次吃冰棍", "1964年", "childhood", "other"),
        ("父亲教我骑自行车", "1965年春", "childhood", "family"),
        ("和邻居小明打架", "1965年秋", "childhood", "other"),
        ("母亲做的红烧肉", "1966年", "childhood", "family"),
        ("小学毕业典礼", "1966年夏", "childhood", "achievement"),
        ("偷看连环画被抓", "1964年", "childhood", "other"),
        ("第一次坐火车去外婆家", "1965年暑假", "childhood", "other"),
        ("学写毛笔字", "1963年", "childhood", "other"),
        ("下雪天打雪仗", "1964年冬", "childhood", "other"),
        ("家里买了第一台收音机", "1966年", "childhood", "family"),
        ("跟着爷爷去钓鱼", "1965年", "childhood", "family"),
        ("参加学校合唱团", "1964年", "childhood", "achievement"),
        ("帮妈妈卖菜", "1966年", "childhood", "family"),
        ("第一次考一百分", "1963年秋", "childhood", "achievement"),
        ("院子里种了一棵桃树", "1964年春", "childhood", "other"),
        ("和姐姐一起放风筝", "1965年春", "childhood", "family"),
        ("邻居家着火了", "1966年冬", "childhood", "other"),
        ("学会游泳", "1965年夏", "childhood", "achievement"),
        ("第一次看电影", "1964年", "childhood", "other"),
    ]

    created = []
    for i in range(count):
        title, time_str, stage, event_type = templates[i % len(templates)]
        # Add index to avoid duplicate filenames
        filename = f"{i:02d}_{title}.md"
        filepath = events_dir / filename
        content = (
            f"# {title}\n\n"
            f"## 基本信息\n"
            f"- **时间**：{time_str}\n"
            f"- **地点**：上海弄堂\n"
            f"- **事件类型**：{event_type}\n\n"
            f"## 事件描述\n"
            f"这是关于「{title}」的一段童年回忆，发生在{time_str}。那时候生活虽然简单，但每一天都充满新鲜感。\n"
        )
        filepath.write_text(content, encoding="utf-8")
        created.append(filepath)

    return created


def verify_story_generation(user_kb: Path) -> list[str]:
    """Verify story generation output: story file, image, and state."""
    failures: list[str] = []

    # Check .story_state.json
    state_file = user_kb / "stories" / ".story_state.json"
    if not state_file.exists():
        failures.append("story_gen: .story_state.json not found")
        return failures

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        failures.append(f"story_gen: failed to read .story_state.json: {e}")
        return failures

    info(f"story_state = {json.dumps(state, ensure_ascii=False)[:500]}")

    stories = state.get("stories", [])
    if not stories:
        failures.append("story_gen: no stories recorded in .story_state.json")
        return failures

    story_entry = stories[0]
    story_id = story_entry.get("story_id", "")
    image_path = story_entry.get("image_path", "")
    image_prompt = story_entry.get("image_prompt", "")

    info(f"story_id = {story_id}")
    info(f"image_path = {image_path!r}")
    info(f"image_prompt = {image_prompt[:80]!r}..." if image_prompt else "image_prompt = (empty)")

    # Verify story .md file exists
    story_file = user_kb / story_entry.get("file_path", "")
    if not story_file.exists():
        failures.append(f"story_gen: story file not found at {story_entry.get('file_path')}")
    else:
        info(f"story file exists: {story_file}")

    # Verify image file exists (if image_path is non-empty)
    if image_path:
        image_file = user_kb / image_path
        if not image_file.exists():
            failures.append(f"story_gen: cover image not found at {image_path}")
        else:
            size = image_file.stat().st_size
            info(f"cover image exists: {image_file} ({size} bytes)")
            if size < 100:
                failures.append(f"story_gen: cover image too small ({size} bytes), likely corrupt")
    else:
        # image_path empty is acceptable (API key might not be configured in test env)
        info("story_gen: image_path is empty (image generation may have been skipped)")

    return failures


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

        # Verify reused=false on first call
        session_started_events = [e for e in start_events if e[0] == "session_started"]
        if session_started_events:
            first_started = session_started_events[0][1]
            if first_started.get("reused") is not False:
                failures.append(
                    f"start: expected reused=false on first call, got {first_started.get('reused')!r}"
                )

        section("Start Interview (Idempotency)")
        reuse_events, reuse_session_id = consume_sse(
            "POST",
            f"{base_url}/api/interview/start",
            json_body={"user_id": user_id},
            capture_session=True,
        )
        if reuse_session_id != session_id:
            failures.append(
                f"start idempotency: expected same session_id={session_id!r}, "
                f"got {reuse_session_id!r}"
            )
        reuse_started = [e for e in reuse_events if e[0] == "session_started"]
        if reuse_started:
            reused_data = reuse_started[0][1]
            if reused_data.get("reused") is not True:
                failures.append(
                    f"start idempotency: expected reused=true, got {reused_data.get('reused')!r}"
                )
        reuse_messages = [e for e in reuse_events if e[0] == "agent_message"]
        if reuse_messages:
            msg_text = reuse_messages[0][1].get("message", "")
            if "当前会话已存在" not in msg_text:
                failures.append(
                    f"start idempotency: expected '当前会话已存在' in message, got {msg_text!r}"
                )

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

        section("Verify Guided State")
        failures.extend(verify_guided_state(user_kb))

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
            # Verify title field exists and is a non-empty string
            title = body.get("title")
            if not isinstance(title, str) or not title.strip():
                failures.append(
                    f"end: expected non-empty string title, got {title!r}"
                )
            else:
                info(f"end: title = {title!r}")
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

        section("Inject Events for Story Generation")
        injected = inject_fake_events(user_kb, "childhood", count=16)
        info(f"Injected {len(injected)} fake events into events/childhood/")

        section("Generate Story")
        story_events, _ = consume_sse(
            "POST",
            f"{base_url}/api/stories/generate",
            json_body={"user_id": user_id},
        )
        if not story_events:
            failures.append("story_gen: no SSE events received from /stories/generate")

        generating_image_events = [e for e in story_events if e[0] == "generating_image"]
        saved_events = [e for e in story_events if e[0] == "saved"]
        completed_events = [e for e in story_events if e[0] == "completed"]
        failed_events = [e for e in story_events if e[0] == "failed"]

        info(f"generating_image events: {len(generating_image_events)}")
        info(f"saved events: {len(saved_events)}")
        info(f"completed events: {len(completed_events)}")
        info(f"failed events: {len(failed_events)}")

        if not saved_events and not completed_events:
            failures.append(
                "story_gen: no 'saved' or 'completed' events — "
                f"failed events: {[e[1] for e in failed_events]}"
            )

        if saved_events:
            saved_data = saved_events[0][1]
            image_path_val = saved_data.get("image_path")
            info(f"saved event image_path = {image_path_val!r}")
            if image_path_val is None:
                failures.append("story_gen: 'saved' event missing image_path field")

        section("Verify Story Generation")
        failures.extend(verify_story_generation(user_kb))

        section("Verify Story List API")
        list_response = requests.get(
            f"{base_url}/api/stories/{user_id}?life_stage=childhood",
            timeout=DEFAULT_TIMEOUT,
        )
        info(f"GET /api/stories/{user_id}?life_stage=childhood -> HTTP {list_response.status_code}")
        if list_response.status_code != 200:
            failures.append(f"story_list: expected 200, got {list_response.status_code}")
        else:
            list_body = list_response.json()
            info(f"story_list body = {json.dumps(list_body, ensure_ascii=False)[:500]}")
            stories_list = list_body.get("stories", [])
            if not stories_list:
                failures.append("story_list: no stories returned")
            else:
                first_story = stories_list[0]
                if "image_path" not in first_story:
                    failures.append("story_list: story missing image_path field")
                else:
                    info(f"story_list image_path = {first_story['image_path']!r}")

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
