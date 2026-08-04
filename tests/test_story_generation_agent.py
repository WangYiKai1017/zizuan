import json
from pathlib import Path

import pytest

from src.agents.story_generation_agent import (
    FIRST_STORY_EVENT_COUNT,
    REQUIRED_EVENT_COUNT,
    SUBSEQUENT_STORY_EVENT_COUNT,
    GeneratedStory,
    LIFE_STAGE_ORDER,
    StoryGenerationAgent,
    StoryOutputInvalidError,
)
from src.service.agent_runners.story_runner import StoryRunner
from src.service.sse_response import SSEEmitter
from src.services.llm_service import LLMCallResult


class StubLLMService:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    async def invoke(self, *args, **kwargs):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def write_event(root: Path, rel_path: str, title: str, year: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# {title}

## 基本信息
- **时间**：{year}
- **地点**：北京
- **事件类型**：other

## 事件描述
这是 {title} 的详细描述。
""",
        encoding="utf-8",
    )


def make_agent(kb_path: Path, results=None) -> StoryGenerationAgent:
    return StoryGenerationAgent(
        kb_path=kb_path,
        llm_service=StubLLMService(results or []),
    )


def test_load_unconsumed_events_migrates_legacy_paths_to_fingerprints(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    write_event(kb, "events/childhood/old.md", "旧事件", "1950")
    write_event(kb, "events/childhood/renamed.md", "旧事件", "1950")
    state_dir = kb / "stories"
    state_dir.mkdir(parents=True)
    (state_dir / ".story_state.json").write_text(
        json.dumps({"generated_event_paths": ["events/childhood/old.md"], "stories": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    events = make_agent(kb).load_unconsumed_events()

    paths = [event.path for event in events]
    assert "events/childhood/old.md" not in paths
    assert "events/childhood/renamed.md" not in paths

    state = json.loads(
        (state_dir / ".story_state.json").read_text(encoding="utf-8")
    )
    assert len(state["generated_event_fingerprints"]) == 1


def test_select_events_uses_earliest_subsequent_batch(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    for i in range(20):
        write_event(kb, f"events/middle_age/event_{i:02d}.md", f"事件{i}", str(1980 + i))

    agent = make_agent(kb)
    selected = agent.select_events(agent.load_unconsumed_events())

    assert len(selected) == REQUIRED_EVENT_COUNT
    assert selected[0].time == "1980"
    assert selected[-1].time == "1989"


def test_select_ready_stage_events_groups_by_path_stage(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    for i in range(2):
        write_event(kb, f"events/childhood/event_{i:02d}.md", f"童年事件{i}", str(1950 + i))
    for i in range(10):
        write_event(kb, f"events/youth/event_{i:02d}.md", f"青年事件{i}", str(1970 + i))
    for i in range(9):
        write_event(kb, f"events/middle_age/event_{i:02d}.md", f"中年事件{i}", str(1990 + i))
    stories_dir = kb / "stories"
    stories_dir.mkdir(parents=True)
    (stories_dir / ".story_state.json").write_text(
        json.dumps({
            "generated_event_paths": [],
            "generated_event_fingerprints": [],
            "stories": [{
                "story_id": "middle_age_story_20260101_000000",
                "file_path": "stories/middle_age_story_20260101_000000.md",
                "life_stage": "middle_age",
            }],
        }),
        encoding="utf-8",
    )

    agent = make_agent(kb)
    ready = agent.select_ready_stage_events(agent.load_unconsumed_events())

    assert list(ready.keys()) == ["youth"]
    assert len(ready["youth"]) == FIRST_STORY_EVENT_COUNT
    assert ready["youth"][0].time == "1970"
    assert ready["youth"][-1].time == "1979"
    assert "childhood" not in ready
    assert "middle_age" not in ready


def test_stage_threshold_is_ten_with_or_without_existing_story(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    agent = make_agent(kb)

    assert FIRST_STORY_EVENT_COUNT == SUBSEQUENT_STORY_EVENT_COUNT == REQUIRED_EVENT_COUNT == 10
    assert agent.required_event_counts_by_stage()["elderly"] == FIRST_STORY_EVENT_COUNT

    stories_dir = kb / "stories"
    stories_dir.mkdir(parents=True)
    (stories_dir / "elderly_story_20260101_000000.md").write_text("# 第一篇", encoding="utf-8")

    assert agent.required_event_counts_by_stage()["elderly"] == SUBSEQUENT_STORY_EVENT_COUNT


def test_subsequent_story_selects_earliest_ten_events(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    for i in range(12):
        write_event(kb, f"events/youth/event_{i:02d}.md", f"青年事件{i}", str(1970 + i))
    stories_dir = kb / "stories"
    stories_dir.mkdir(parents=True)
    (stories_dir / "youth_story_20260101_000000.md").write_text("# 第一篇", encoding="utf-8")

    agent = make_agent(kb)
    ready = agent.select_ready_stage_events(agent.load_unconsumed_events())

    assert len(ready["youth"]) == SUBSEQUENT_STORY_EVENT_COUNT
    assert ready["youth"][0].time == "1970"
    assert ready["youth"][-1].time == "1979"


def test_life_stage_order_matches_generation_order() -> None:
    assert LIFE_STAGE_ORDER == ("childhood", "youth", "middle_age", "elderly")


def test_system_prompt_keeps_json_example_literal(tmp_path: Path) -> None:
    prompt = make_agent(tmp_path / "user001")._build_system_prompt("childhood")

    assert '{\n  "title": "故事标题",' in prompt
    assert '"body": "故事正文"' in prompt


def test_user_prompt_uses_actual_event_count(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    for i in range(FIRST_STORY_EVENT_COUNT):
        write_event(kb, f"events/elderly/event_{i:02d}.md", f"晚年事件{i}", str(2020 + i))
    agent = make_agent(kb)
    events = agent.select_events(agent.load_unconsumed_events(), FIRST_STORY_EVENT_COUNT)

    prompt = agent._build_user_prompt(events, "elderly")

    assert "下面 10 个来自老年时期的事件" in prompt
    assert "15 个" not in prompt


@pytest.mark.asyncio
async def test_runner_reports_dynamic_thresholds_and_closes_failed_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb = tmp_path / "user001"
    for i in range(FIRST_STORY_EVENT_COUNT - 1):
        write_event(kb, f"events/childhood/event_{i:02d}.md", f"童年事件{i}", str(1950 + i))
    agent = make_agent(kb)
    emitter = SSEEmitter()
    runner = StoryRunner(user_id="user001", session_id="sess_test", emitter=emitter)
    monkeypatch.setattr(runner, "_get_kb_path", lambda: str(kb))
    monkeypatch.setattr(runner, "_create_agent", lambda _kb_path: agent)

    await runner.run()

    assert [event["event"] for event in emitter.events] == [
        "task_started",
        "scanning",
        "failed",
        "done",
    ]
    scanning = emitter.events[1]["data"]
    assert scanning["available_event_counts_by_stage"]["childhood"] == 9
    assert scanning["required_event_counts_by_stage"]["childhood"] == FIRST_STORY_EVENT_COUNT
    failed = emitter.events[2]["data"]
    assert failed["error_code"] == "INSUFFICIENT_EVENTS"
    sent_events = [event async for event in emitter.stream()]
    assert len(sent_events) == 4


def test_save_story_then_marks_events_consumed(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    for i in range(REQUIRED_EVENT_COUNT):
        write_event(kb, f"events/childhood/event_{i:02d}.md", f"事件{i}", str(1950 + i))
    agent = make_agent(kb)
    events = agent.select_events(agent.load_unconsumed_events())

    saved = agent.save_story_and_mark_consumed(
        GeneratedStory(title="一路走来", body="这是一个足够长的故事正文。" * 10),
        events,
        life_stage="childhood",
    )

    assert (kb / saved.story_path).exists()
    assert saved.life_stage == "childhood"
    assert saved.story_id.startswith("childhood_story_")
    state = json.loads((kb / "stories" / ".story_state.json").read_text(encoding="utf-8"))
    assert len(state["generated_event_paths"]) == REQUIRED_EVENT_COUNT
    assert len(state["generated_event_fingerprints"]) == REQUIRED_EVENT_COUNT
    assert state["stories"][0]["story_id"] == saved.story_id
    assert state["stories"][0]["file_path"] == saved.story_path
    assert state["stories"][0]["life_stage"] == "childhood"
    story_text = (kb / saved.story_path).read_text(encoding="utf-8")
    assert "来源时期：童年时期" in story_text


def test_event_fingerprint_survives_move_but_changes_after_rewrite(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    original_path = kb / "events/childhood/original.md"
    write_event(kb, "events/childhood/original.md", "院子里的往事", "1950")
    content = original_path.read_text(encoding="utf-8")
    fingerprint = StoryGenerationAgent._event_fingerprint(content)

    state_dir = kb / "stories"
    state_dir.mkdir(parents=True)
    (state_dir / ".story_state.json").write_text(
        json.dumps({
            "generated_event_paths": ["events/childhood/original.md"],
            "generated_event_fingerprints": [fingerprint],
            "stories": [],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    moved_path = kb / "events/youth/moved.md"
    moved_path.parent.mkdir(parents=True)
    original_path.rename(moved_path)

    agent = make_agent(kb)
    assert agent.load_unconsumed_events() == []

    moved_path.write_text(content + "\n新增的明确细节。\n", encoding="utf-8")
    events = agent.load_unconsumed_events()

    assert [event.path for event in events] == ["events/youth/moved.md"]
    assert events[0].fingerprint != fingerprint


@pytest.mark.asyncio
async def test_generate_story_retries_invalid_output(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    for i in range(REQUIRED_EVENT_COUNT):
        write_event(kb, f"events/childhood/event_{i:02d}.md", f"事件{i}", str(1950 + i))
    valid_body = "我沿着这些往事慢慢回想。" * 20
    agent = make_agent(kb, [
        LLMCallResult(success=True, content="not-json"),
        LLMCallResult(success=True, content=json.dumps({"title": "往事", "body": valid_body}, ensure_ascii=False)),
    ])

    story = await agent.generate_story(
        agent.select_events(agent.load_unconsumed_events()),
        life_stage="childhood",
    )

    assert story.title == "往事"
    assert story.body == valid_body
    assert agent.llm_service.calls == 2


@pytest.mark.asyncio
async def test_generate_story_fails_after_retry(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    for i in range(REQUIRED_EVENT_COUNT):
        write_event(kb, f"events/childhood/event_{i:02d}.md", f"事件{i}", str(1950 + i))
    agent = make_agent(kb, [
        LLMCallResult(success=True, content="not-json"),
        LLMCallResult(success=True, content="still-not-json"),
    ])

    with pytest.raises(StoryOutputInvalidError):
        await agent.generate_story(
            agent.select_events(agent.load_unconsumed_events()),
            life_stage="childhood",
        )
    assert agent.llm_service.calls == 2
