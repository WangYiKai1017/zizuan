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
    warn,
)

KB_ROOT = PROJECT_ROOT / "knowledge_base"
LOG_DIR = PROJECT_ROOT / "logs"
FIXTURE_KB_DIR = _INTEGRATION_DIR / "fixtures" / "biography_kb"


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

def create_test_kb(test_user_id: str) -> Path:
    """Copy fixture KB data to a fresh test user directory.

    The biography/ directory is intentionally NOT copied so the test starts
    from scratch and exercises the full outline → write pipeline.
    """
    if not FIXTURE_KB_DIR.exists():
        raise RuntimeError(f"Fixture KB not found: {FIXTURE_KB_DIR}")

    test_kb = KB_ROOT / test_user_id
    if test_kb.exists():
        shutil.rmtree(test_kb)
    test_kb.mkdir(parents=True)

    # Copy the directories the outline agent scans.
    for subdir in ("events", "people", "timeline", "themes", "sessions"):
        src = FIXTURE_KB_DIR / subdir
        if src.exists():
            shutil.copytree(src, test_kb / subdir)

    # Copy metadata files needed for outline generation.
    for filename in ("user.md", "index.md", "summary_index.md"):
        src = FIXTURE_KB_DIR / filename
        if src.exists():
            shutil.copy2(src, test_kb / filename)

    # Ensure biography/ exists but is empty (the agent will create outline.yaml).
    (test_kb / "biography" / "chapters").mkdir(parents=True, exist_ok=True)

    info(f"Created test KB from fixture → {test_kb}")
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
    test_user_id = f"e2e_biography_{int(time.time())}"

    proc: subprocess.Popen[Any] | None = None
    test_kb: Path | None = None
    failures: list[str] = []
    first_run_word_count = 0
    first_run_chapter_ids: set = set()

    section("Setup")
    info(f"PROJECT_ROOT    = {PROJECT_ROOT}")
    info(f"BASE_URL        = {base_url}")
    info(f"FIXTURE_KB_DIR  = {FIXTURE_KB_DIR}")
    info(f"TEST_USER_ID    = {test_user_id}")

    try:
        # ---- Setup -------------------------------------------------------
        test_kb = create_test_kb(test_user_id)
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

                first_run_chapter_ids = {
                    ch.get("id") for ch in chapters if isinstance(ch, dict)
                }

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
                first_run_word_count = total_wc
                info(f"content preview    = {content[:200]!r}...")

                if not content.strip():
                    failures.append("get full: content is empty")
                if total_wc == 0:
                    failures.append("get full: total_word_count is 0")
        except requests.RequestException as exc:
            failures.append(f"get full: network error: {exc}")

        # ---- Incremental Update Tests ------------------------------------

        # Step 7: Add new events to middle_age
        section("Step 7: Add new events to middle_age (simulate user activity)")
        new_events = {
            "结婚并在北京安家.md": (
                "# 结婚并在北京安家\n\n"
                "- **时间**: 2015年\n"
                "- **地点**: 北京\n\n"
                "## 事件描述\n\n"
                "2015年在北京结婚，和妻子一起在这座城市安家。当时工作压力很大，"
                "但妻子的支持让我能够全身心投入事业。我们在北京租了一间小公寓，"
                "虽然不大，但那是我们第一个属于自己的家。\n\n"
                "## 关键细节\n\n"
                "- 婚礼在北京举办，规模不大，只请了最亲近的家人和朋友\n"
                "- 婚后住在朝阳区的一间两居室，月租不便宜\n"
                "- 妻子在生活上照顾我很多，让我能专注于工作\n"
            ),
            "女儿出生.md": (
                "# 女儿出生\n\n"
                "- **时间**: 2017年\n"
                "- **地点**: 北京\n\n"
                "## 事件描述\n\n"
                "2017年女儿出生，是我人生中最幸福的时刻之一。第一次抱起她的时候，"
                "感觉自己整个人都被融化了。从那以后，工作再忙也会抽时间陪她，"
                "不想错过她成长的每一个瞬间。\n\n"
                "## 关键细节\n\n"
                "- 女儿在北京出生，妻子顺产，过程很顺利\n"
                "- 给她取名字的时候花了很多心思\n"
                "- 第一次叫爸爸的时候，我激动得差点哭出来\n"
            ),
            "离开咨询行业创办AI公司.md": (
                "# 离开咨询行业创办AI公司\n\n"
                "- **时间**: 2020年\n"
                "- **地点**: 北京\n\n"
                "## 事件描述\n\n"
                "2020年做了一个重大决定：离开做了多年的咨询行业，创办一家AI公司。"
                "当时AI技术发展很快，我觉得这是一个难得的机会。很多人不理解我的选择，"
                "觉得咨询行业已经很稳定了，但我知道如果不抓住这个机会，以后一定会后悔。"
                "创业的过程非常艰辛，但也让我学到了很多。\n\n"
                "## 关键细节\n\n"
                "- 辞职的时候，同事和老板都很惊讶\n"
                "- 创业初期只有3个人，在一间很小的办公室\n"
                "- 第一年几乎没有收入，靠积蓄和妻子的工资支撑\n"
                "- 最困难的时候想过放弃，但还是坚持下来了\n"
            ),
            "决定带家人移居上海.md": (
                "# 决定带家人移居上海\n\n"
                "- **时间**: 2022年\n"
                "- **地点**: 上海\n\n"
                "## 事件描述\n\n"
                "2022年决定带全家搬到上海。主要原因是女儿要上小学了，"
                "上海的教育资源更好一些，而且妻子的家人也在上海，可以互相照应。"
                "离开北京有些不舍，毕竟在那里生活了快十年，但为了家庭整体考虑，"
                "这是一个正确的决定。\n\n"
                "## 关键细节\n\n"
                "- 搬家前在北京生活了近十年\n"
                "- 选择上海主要为了女儿的教育和家人的支持\n"
                "- 妻子对这个决定非常支持\n"
                "- 到上海后重新适应了新的生活环境\n"
            ),
        }
        if test_kb is not None:
            middle_age_dir = test_kb / "events" / "middle_age"
            middle_age_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in new_events.items():
                (middle_age_dir / filename).write_text(content, encoding="utf-8")
            info(f"Added {len(new_events)} new events to events/middle_age/")

        # Step 8: Second outline generation (incremental)
        section("Step 8: Second POST /api/biography/outline/generate (incremental)")
        inc_outline_events = consume_sse(
            "POST",
            f"{base_url}/api/biography/outline/generate",
            json_body={"user_id": test_user_id},
            request_timeout=args.request_timeout,
        )
        if not inc_outline_events:
            failures.append("incremental outline: no SSE events received")
        inc_completed = [e for e in inc_outline_events if e[0] == "completed"]
        if not inc_completed:
            warn("incremental outline: no 'completed' event seen")

        # Step 9: GET outline, check statuses
        section("Step 9: GET outline after incremental update")
        r = requests.get(outline_url, timeout=DEFAULT_TIMEOUT)
        info(f"GET {outline_url} → HTTP {r.status_code}")
        new_draft_ids: list[str] = []
        outdated_ids: list[str] = []
        written_ids: list[str] = []
        if r.status_code != 200:
            failures.append(f"incremental get outline: expected 200, got {r.status_code}")
        else:
            inc_outline = r.json()
            inc_chapters = inc_outline.get("chapters") or []
            info(f"total chapters after incremental: {len(inc_chapters)}")

            for ch in inc_chapters:
                if not isinstance(ch, dict):
                    continue
                ch_id = ch.get("id", "")
                status = ch.get("status", "")
                if ch_id not in first_run_chapter_ids:
                    new_draft_ids.append(ch_id)
                    info(f"  NEW DRAFT:     {ch_id} - {ch.get('title', '')!r}")
                elif status == "outdated":
                    outdated_ids.append(ch_id)
                    info(f"  OUTDATED:      {ch_id} - {ch.get('title', '')!r}")
                elif status == "written":
                    written_ids.append(ch_id)
                    info(f"  WRITTEN (ok):  {ch_id} - {ch.get('title', '')!r}")

            if not new_draft_ids and not outdated_ids:
                failures.append(
                    "incremental outline: no new DRAFT or OUTDATED chapters detected; "
                    f"first_run_ids={first_run_chapter_ids}, "
                    f"all statuses: {[ch.get('status') for ch in inc_chapters if isinstance(ch, dict)]}"
                )

        # Step 10: Confirm all DRAFT and OUTDATED chapters
        section("Step 10: PUT confirm all DRAFT and OUTDATED chapters")
        to_confirm = new_draft_ids + outdated_ids
        info(f"chapters to confirm: {to_confirm}")
        confirmed_ok = 0
        for ch_id in to_confirm:
            confirm_url = (
                f"{base_url}/api/biography/outline/{test_user_id}"
                f"/chapters/{ch_id}/confirm"
            )
            try:
                r = requests.put(
                    confirm_url,
                    json={"notes": "e2e incremental confirm"},
                    timeout=DEFAULT_TIMEOUT,
                )
                if r.status_code == 200:
                    body = r.json()
                    if body.get("status") == "confirmed":
                        confirmed_ok += 1
                        info(f"  confirmed: {ch_id}")
                    else:
                        failures.append(
                            f"confirm {ch_id}: expected status='confirmed', "
                            f"got {body.get('status')!r}"
                        )
                else:
                    failures.append(
                        f"confirm {ch_id}: expected 200, got {r.status_code}: {r.text[:200]}"
                    )
            except requests.RequestException as exc:
                failures.append(f"confirm {ch_id}: network error: {exc}")

        info(f"confirmed {confirmed_ok}/{len(to_confirm)} chapters")

        # Step 11: Second writing run
        section("Step 11: Second POST /api/biography/writing/run")
        inc_writing_events = consume_sse(
            "POST",
            f"{base_url}/api/biography/writing/run",
            json_body={"user_id": test_user_id},
            request_timeout=args.request_timeout,
        )
        if not inc_writing_events:
            failures.append("incremental writing: no SSE events received")
        inc_writing_completed = [e for e in inc_writing_events if e[0] == "completed"]
        if not inc_writing_completed:
            warn("incremental writing: no 'completed' event")

        # Step 12: GET full, verify word count increased
        section("Step 12: GET full biography after incremental update")
        r = requests.get(full_url, timeout=DEFAULT_TIMEOUT)
        info(f"GET {full_url} → HTTP {r.status_code}")
        if r.status_code != 200:
            failures.append(f"incremental get full: expected 200, got {r.status_code}")
        else:
            body = r.json()
            new_wc = body.get("total_word_count", 0)
            info(f"first run word_count  = {first_run_word_count}")
            info(f"second run word_count = {new_wc}")
            if new_wc <= first_run_word_count:
                failures.append(
                    f"incremental full: expected word_count > {first_run_word_count}, "
                    f"got {new_wc}"
                )
            info(f"full biography updated: {first_run_word_count} → {new_wc} bytes")

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
