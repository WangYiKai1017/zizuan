import json
from pathlib import Path

import pytest

from src.agents.story_generation_agent import (
    REQUIRED_EVENT_COUNT,
    GeneratedStory,
    StoryGenerationAgent,
    StoryOutputInvalidError,
)
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


def test_load_unconsumed_events_filters_consumed_paths(tmp_path: Path) -> None:
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
    assert "events/childhood/renamed.md" in paths


def test_select_events_uses_earliest_15(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    for i in range(20):
        write_event(kb, f"events/middle_age/event_{i:02d}.md", f"事件{i}", str(1980 + i))

    agent = make_agent(kb)
    selected = agent.select_events(agent.load_unconsumed_events())

    assert len(selected) == REQUIRED_EVENT_COUNT
    assert selected[0].time == "1980"
    assert selected[-1].time == "1994"


def test_save_story_then_marks_events_consumed(tmp_path: Path) -> None:
    kb = tmp_path / "user001"
    for i in range(REQUIRED_EVENT_COUNT):
        write_event(kb, f"events/childhood/event_{i:02d}.md", f"事件{i}", str(1950 + i))
    agent = make_agent(kb)
    events = agent.select_events(agent.load_unconsumed_events())

    saved = agent.save_story_and_mark_consumed(
        GeneratedStory(title="一路走来", body="这是一个足够长的故事正文。" * 10),
        events,
    )

    assert (kb / saved.story_path).exists()
    state = json.loads((kb / "stories" / ".story_state.json").read_text(encoding="utf-8"))
    assert len(state["generated_event_paths"]) == REQUIRED_EVENT_COUNT
    assert state["stories"][0]["story_id"] == saved.story_id
    assert state["stories"][0]["file_path"] == saved.story_path


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

    story = await agent.generate_story(agent.select_events(agent.load_unconsumed_events()))

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
        await agent.generate_story(agent.select_events(agent.load_unconsumed_events()))
    assert agent.llm_service.calls == 2
