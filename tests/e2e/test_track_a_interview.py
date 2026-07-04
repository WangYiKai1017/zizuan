#!/usr/bin/env python3
"""Happy-path end-to-end test for the Interview HTTP/SSE API.

The script starts a real backend service, calls the interview flow, ends the
session, and inspects generated knowledge-base files.

Answers to interview questions are generated dynamically using DeepSeek
(OpenAI-compatible API configured in .env) so that the test exercises real
LLM-in-the-loop behaviour instead of relying on hardcoded scripts.

Usage:
    ./.venv/bin/python tests/e2e/test_track_a_interview.py

Optional:
    ... --port 10080 --user-id e2e_interview_001 --rounds 8 --cleanup-kb
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import openai
from dotenv import load_dotenv

# Allow running directly from the repository root.
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent.parent
# Add tests/integration/ to path for _common
_INTEGRATION_DIR = THIS_DIR.parent / "integration"
if str(_INTEGRATION_DIR) not in sys.path:
    sys.path.insert(0, str(_INTEGRATION_DIR))

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

# Profile sent to prefill endpoint (replaces direct user.md writing)
PREFILL_PROFILE = {
    "wechat_id": "wx_e2e_interview",
    "name": "林建华",
    "age": 68,
    "birth_date": "1958-03-12",
    "gender": "male",
}

# Claude system prompt for generating realistic interview answers
ANSWER_SYSTEM_PROMPT = """\
你正在扮演一位名叫林建华的68岁退休教师，接受一次人生回忆采访。

人物背景：
- 男，1958年生于上海
- 6-12岁在上海芳草地小学读书，那时候学校离家不算近，每天走路上学
- 12-18岁在朝阳外国语学校读初中和高中，学习压力不小，但交到了好朋友
- 初中语文老师王老师对你影响很大，鼓励你写作，推荐你参加作文比赛
- 后来选了中文系，毕业后当了语文老师，教了三十年书
- 已婚，有一个女儿，现在和妻子住在上海
- 性格温和，有文化修养，回忆往事时带着感情

回答要求：
- 用第一人称口语回答，语气自然，像在和采访者聊天
- 每次回答提供具体的时间、地点、人物和细节
- 可以穿插感慨和反思，但不要每次都说
- 不要编造过于戏剧化的情节，保持普通人生活的真实感
- 回答控制在3-5句话，不要太长
- 直接回答，不要说"好的"、"让我想想"之类的开场白
"""


def generate_answer(client: openai.OpenAI, model: str, question: str) -> str:
    """Use DeepSeek (OpenAI-compatible) to generate a realistic interview answer."""
    response = client.chat.completions.create(
        model=model,
        max_tokens=300,
        messages=[
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
    )
    return response.choices[0].message.content or ""


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
        "--rounds",
        type=int,
        default=6,
        help="Number of interview message rounds to run (default: 6).",
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
    """Create KB directory structure only — user.md is created by the prefill API call."""
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


def extract_markdown_section(content: str, heading: str) -> str:
    """Extract a second-level markdown section by heading text."""
    target = f"## {heading}"
    lines = content.splitlines()
    start: int | None = None
    for idx, line in enumerate(lines):
        if line.strip() == target:
            start = idx + 1
            break
    if start is None:
        return ""

    section_lines: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        section_lines.append(line)
    return "\n".join(section_lines).strip()


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from a judge response that may include markdown fences."""
    raw = text.strip()
    fence = chr(96) * 3
    if raw.startswith(fence):
        raw = raw.split(fence, 2)[1]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end >= start:
        raw = raw[start : end + 1]
    return json.loads(raw)


def judge_session_summary(
    client: openai.OpenAI,
    model: str,
    *,
    transcript: str,
    summary_text: str,
) -> dict[str, Any]:
    """Use an LLM judge for non-trivial summary quality checks."""
    prompt = f"""你是一个严格的采访质检员。请判断“本次采访摘要”是否适合作为下一次开场时回顾“上次聊了什么”的依据。

评分标准：
1. 摘要必须具体概括本轮真实聊天内容，包含至少一个具体故事、人物、地点、场景或事件。
2. 摘要必须能从对话记录中得到支持，不能引入对话里没有的旧知识库内容。
3. 摘要不能只是结束寒暄，例如“今天聊得很愉快”“谢谢分享”“下次继续聊”“祝生活愉快”。
4. 摘要可以简短，但必须足够让下次开场准确承接。

请只输出 JSON：
{{
  "pass": true 或 false,
  "score": 0到1之间的小数,
  "reason": "一句话说明",
  "grounded_topics": ["摘要中被对话支持的具体主题"]
}}

【对话记录】
{transcript}

【本次采访摘要】
{summary_text}
"""
    response = client.chat.completions.create(
        model=model,
        max_tokens=400,
        temperature=0,
        messages=[
            {"role": "system", "content": "你只输出合法 JSON，不输出任何额外解释。"},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    return extract_json_object(content)


def read_latest_session_summary(user_kb: Path) -> tuple[Path | None, str]:
    """Return latest session archive path and its factual summary section."""
    session_files = sorted((user_kb / "sessions").glob("session_*.md"))
    if not session_files:
        return None, ""

    latest_session = session_files[-1]
    content = latest_session.read_text(encoding="utf-8")
    return latest_session, extract_markdown_section(content, "本次采访摘要")


def verify_session_summary_with_llm_judge(
    user_kb: Path,
    client: openai.OpenAI,
    model: str,
    transcript: list[str],
) -> list[str]:
    """Verify latest session summary quality using an LLM-as-judge check."""
    failures: list[str] = []
    latest_session, summary_text = read_latest_session_summary(user_kb)
    if latest_session is None:
        return ["session_summary_judge: no session archive files found"]

    info(f"session_summary_judge: latest session = {latest_session}")
    info(f"session_summary_judge: summary = {summary_text!r}")

    if not summary_text:
        return ["session_summary_judge: latest session summary is empty"]

    generic_terms = ["聊天很愉快", "谢谢您的分享", "感谢您的分享", "下次继续聊", "祝您生活愉快"]
    compact_summary = "".join(summary_text.split())
    if any(term in compact_summary for term in generic_terms) and len(compact_summary) < 80:
        failures.append(
            "session_summary_judge: summary looks like a generic closing pleasantry before LLM judge"
        )

    transcript_text = "\n".join(transcript[-24:])
    if not transcript_text.strip():
        return failures + ["session_summary_judge: transcript is empty"]

    try:
        verdict = judge_session_summary(
            client,
            model,
            transcript=transcript_text,
            summary_text=summary_text,
        )
    except Exception as exc:
        return failures + [f"session_summary_judge: judge call failed: {exc}"]

    info(f"session_summary_judge verdict = {json.dumps(verdict, ensure_ascii=False)}")
    passed = verdict.get("pass") is True
    try:
        score = float(verdict.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    if not passed or score < 0.75:
        failures.append(
            "session_summary_judge: summary failed LLM judge "
            f"(pass={verdict.get('pass')!r}, score={score}, reason={verdict.get('reason')!r})"
        )

    return failures


def judge_restart_opening(
    client: openai.OpenAI,
    model: str,
    *,
    previous_summary: str,
    opening_message: str,
) -> dict[str, Any]:
    """Use an LLM judge to verify restart opening is grounded in latest session summary."""
    prompt = f"""你是一个严格的采访质检员。请判断第二次 /start 的开场白是否正确使用了“上一次 session 的摘要”。

评分标准：
1. 开场白必须自然承接上次摘要中的至少一个具体事实、主题或场景。
2. 开场白不能把摘要里没有的旧知识库内容说成“上次聊到”。
3. 开场白可以继续引出新的采访问题，但不能脱离上次摘要。
4. 如果开场白只是泛泛欢迎，或者提到与摘要无关的故事，应判失败。

请只输出 JSON：
{{
  "pass": true 或 false,
  "score": 0到1之间的小数,
  "reason": "一句话说明",
  "summary_topics_used": ["开场白中实际使用的摘要主题"]
}}

【上一次 session 摘要】
{previous_summary}

【第二次 /start 开场白】
{opening_message}
"""
    response = client.chat.completions.create(
        model=model,
        max_tokens=400,
        temperature=0,
        messages=[
            {"role": "system", "content": "你只输出合法 JSON，不输出任何额外解释。"},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    return extract_json_object(content)


def verify_restart_opening_with_llm_judge(
    client: openai.OpenAI,
    model: str,
    *,
    previous_summary: str,
    opening_message: str,
) -> list[str]:
    """Verify second /start opening uses the previous session summary."""
    failures: list[str] = []
    if not previous_summary.strip():
        return ["restart_opening_judge: previous session summary is empty"]
    if not opening_message.strip():
        return ["restart_opening_judge: opening message is empty"]

    try:
        verdict = judge_restart_opening(
            client,
            model,
            previous_summary=previous_summary,
            opening_message=opening_message,
        )
    except Exception as exc:
        return [f"restart_opening_judge: judge call failed: {exc}"]

    info(f"restart_opening_judge verdict = {json.dumps(verdict, ensure_ascii=False)}")
    passed = verdict.get("pass") is True
    try:
        score = float(verdict.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    if not passed or score < 0.75:
        failures.append(
            "restart_opening_judge: opening failed LLM judge "
            f"(pass={verdict.get('pass')!r}, score={score}, reason={verdict.get('reason')!r})"
        )

    return failures




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


def verify_guided_state(user_kb: Path, rounds: int) -> list[str]:
    """Verify guided state file exists and is structurally valid."""
    failures: list[str] = []
    state = read_guided_state(user_kb)
    if not state:
        failures.append("guided_state: file missing or unreadable")
        return failures

    info(f"guided_state = {json.dumps(state, ensure_ascii=False)}")

    completed_ids = state.get("completed_question_ids", [])
    info(f"completed_question_ids ({len(completed_ids)} total) = {completed_ids}")

    # After N rounds, guided phase should not be complete (64 preset questions)
    if state.get("guided_completed") is True:
        failures.append(
            f"guided_state: guided_completed=true after only {rounds} rounds (64 preset questions)"
        )

    # current_question_id should not be in completed list
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
        info("story_gen: image_path is empty (image generation may have been skipped)")

    # Verify illustration files
    illustration_paths = story_entry.get("illustration_paths", [])
    info(f"illustration_paths = {illustration_paths}")
    if not illustration_paths:
        info("story_gen: illustration_paths is empty (image generation may have been skipped)")
    else:
        for illust_path in illustration_paths:
            illust_file = user_kb / illust_path
            if not illust_file.exists():
                failures.append(f"story_gen: illustration not found at {illust_path}")
            else:
                size = illust_file.stat().st_size
                info(f"illustration exists: {illust_file} ({size} bytes)")
                if size < 100:
                    failures.append(f"story_gen: illustration too small ({size} bytes): {illust_path}")

    return failures


def verify_event_classification(user_kb: Path) -> list[str]:
    """Verify that interview messages produced event files in valid stage directories."""
    failures: list[str] = []

    events_root = user_kb / "events"
    stage_files: dict[str, list[Path]] = {}
    for stage_dir in sorted(events_root.iterdir()):
        if stage_dir.is_dir() and not stage_dir.name.startswith("."):
            files = [f for f in stage_dir.glob("*.md") if not f.name.startswith(".")]
            if files:
                stage_files[stage_dir.name] = files

    info(f"event stages with files: {', '.join(f'{k}({len(v)})' for k, v in stage_files.items())}")
    total_events = sum(len(v) for v in stage_files.values())

    # The pre-seeded event counts as 1; dynamic interview should add more
    if total_events < 2:
        failures.append(
            f"kb: expected at least 2 event files (1 seeded + dynamic), got {total_events}"
        )

    # At least one valid life-stage directory should have events
    valid_stages = {"childhood", "youth", "middle_age", "elderly"}
    found_stages = set(stage_files.keys())
    if not found_stages & valid_stages:
        failures.append(
            f"kb: no events in valid life-stage directories, found: {found_stages}"
        )

    # Session archive checks (unchanged — these don't depend on content)
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
    interview_transcript: list[str] = []

    # DeepSeek (OpenAI-compatible) client for generating dynamic interview answers
    load_dotenv(PROJECT_ROOT / ".env")
    deepseek_api_key = os.environ.get("DEEPSEEK_APIKEY", "")
    deepseek_url = os.environ.get("DEEPSEEK_URL", "")
    deepseek_model = os.environ.get("DEEPSEEK_MODEL_NAME", "deepseek-v4-flash")
    if not deepseek_api_key or not deepseek_url:
        err("DEEPSEEK_APIKEY and DEEPSEEK_URL must be set in .env or environment")
        return summarize("Interview API happy path E2E", False, ["DeepSeek config missing"])
    answer_client = openai.OpenAI(api_key=deepseek_api_key, base_url=deepseek_url)

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

        section("Prefill Profile")
        prefill_response = requests.post(
            f"{base_url}/api/interview/profile/prefill",
            json={"user_id": user_id, **PREFILL_PROFILE},
            timeout=DEFAULT_TIMEOUT,
        )
        info(f"POST /api/interview/profile/prefill -> HTTP {prefill_response.status_code}")
        if prefill_response.status_code != 200:
            failures.append(f"prefill: expected 200, got {prefill_response.status_code}")
            info(f"prefill body = {prefill_response.text[:500]}")
        else:
            prefill_body = prefill_response.json()
            info(f"prefill profile_complete = {prefill_body.get('profile_complete')}")
            info(f"prefill missing_fields  = {prefill_body.get('missing_required_fields')}")
            if prefill_body.get("status") != "ok":
                failures.append(f"prefill: expected status='ok', got {prefill_body.get('status')!r}")
            if not (user_kb / "user.md").exists():
                failures.append("prefill: user.md was not created")
            else:
                info(f"user.md created at {user_kb / 'user.md'}")

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

        # Capture the opening question from start_events
        agent_msgs = [e[1] for e in start_events if e[0] == "agent_message"]
        current_question = agent_msgs[-1].get("message", "") if agent_msgs else ""
        info(f"opening question = {current_question!r}")
        if current_question:
            interview_transcript.append(f"助手: {current_question}")

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

        section("Dynamic Interview (Claude-powered answers)")
        for round_idx in range(1, args.rounds + 1):
            if not current_question:
                info(f"round {round_idx}: no question to answer, stopping")
                break
            answer = generate_answer(answer_client, deepseek_model, current_question)
            info(f"round {round_idx} question: {current_question[:80]}...")
            info(f"round {round_idx} answer:   {answer[:80]}...")
            interview_transcript.append(f"用户: {answer}")
            message_events, _ = consume_sse(
                "POST",
                f"{base_url}/api/interview/message",
                json_body={
                    "user_id": user_id,
                    "session_id": session_id,
                    "message": answer,
                },
            )
            if not message_events:
                failures.append(f"round {round_idx}: no SSE events received")
                break
            # Extract next question from agent_message events
            next_msgs = [e[1] for e in message_events if e[0] == "agent_message"]
            current_question = next_msgs[-1].get("message", "") if next_msgs else ""
            if current_question:
                interview_transcript.append(f"助手: {current_question}")

        section("Verify Guided State")
        failures.extend(verify_guided_state(user_kb, args.rounds))

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

        section("Judge Session Summary")
        failures.extend(
            verify_session_summary_with_llm_judge(
                user_kb,
                answer_client,
                deepseek_model,
                interview_transcript,
            )
        )
        previous_summary_path, previous_summary = read_latest_session_summary(user_kb)
        if previous_summary_path is not None:
            info(f"previous session summary source = {previous_summary_path}")

        section("Status After End")
        ended_status_response = requests.get(status_url, timeout=DEFAULT_TIMEOUT)
        info(f"GET {status_url} -> HTTP {ended_status_response.status_code}")
        info(f"body = {ended_status_response.text[:500]}")
        if ended_status_response.status_code != 404:
            failures.append(
                f"status after end: expected 404, got {ended_status_response.status_code}"
            )

        section("End Interview (Idempotency)")
        end_again_response = requests.post(
            f"{base_url}/api/interview/end",
            json={"user_id": user_id, "session_id": session_id},
            timeout=args.request_timeout,
        )
        info(f"POST /api/interview/end (again) -> HTTP {end_again_response.status_code}")
        info(f"body = {end_again_response.text[:500]}")
        if end_again_response.status_code != 200:
            failures.append(
                f"end idempotency: expected 200 on second call, got {end_again_response.status_code}"
            )
        else:
            end_again_body = end_again_response.json()
            if end_again_body.get("status") != "already_ended":
                failures.append(
                    f"end idempotency: expected status='already_ended', "
                    f"got {end_again_body.get('status')!r}"
                )

        section("Restart Interview Uses Previous Summary")
        restart_events, restart_session_id = consume_sse(
            "POST",
            f"{base_url}/api/interview/start",
            json_body={"user_id": user_id},
            capture_session=True,
        )
        if not restart_events:
            failures.append("restart start: no SSE events received")
        if not restart_session_id:
            failures.append("restart start: no session_id captured")
        elif restart_session_id == session_id:
            failures.append(
                f"restart start: expected a new session id after end, got original {restart_session_id!r}"
            )
        restart_started = [e for e in restart_events if e[0] == "session_started"]
        if restart_started:
            restart_data = restart_started[0][1]
            if restart_data.get("reused") is not False:
                failures.append(
                    f"restart start: expected reused=false, got {restart_data.get('reused')!r}"
                )

        restart_messages = [e[1] for e in restart_events if e[0] == "agent_message"]
        restart_opening = restart_messages[-1].get("message", "") if restart_messages else ""
        info(f"restart opening = {restart_opening!r}")
        failures.extend(
            verify_restart_opening_with_llm_judge(
                answer_client,
                deepseek_model,
                previous_summary=previous_summary,
                opening_message=restart_opening,
            )
        )

        if restart_session_id:
            restart_end_response = requests.post(
                f"{base_url}/api/interview/end",
                json={"user_id": user_id, "session_id": restart_session_id},
                timeout=args.request_timeout,
            )
            info(f"POST /api/interview/end (restart session) -> HTTP {restart_end_response.status_code}")
            info(f"body = {restart_end_response.text[:500]}")
            if restart_end_response.status_code != 200:
                failures.append(
                    "restart end: expected 200 when closing restart session, "
                    f"got {restart_end_response.status_code}"
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
            illust_paths_val = saved_data.get("illustration_paths")
            info(f"saved event image_path = {image_path_val!r}")
            info(f"saved event illustration_paths = {illust_paths_val!r}")
            if image_path_val is None:
                failures.append("story_gen: 'saved' event missing image_path field")
            if illust_paths_val is None:
                failures.append("story_gen: 'saved' event missing illustration_paths field")

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
                if "illustration_paths" not in first_story:
                    failures.append("story_list: story missing illustration_paths field")
                else:
                    info(f"story_list illustration_paths = {first_story['illustration_paths']!r}")

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
