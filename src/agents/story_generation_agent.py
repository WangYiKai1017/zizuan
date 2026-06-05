"""Story generation agent.

Generate one standalone first-person story from the earliest 15 unconsumed
event files in a user's knowledge base.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.services.llm_service import LLMCallResult, LLMService
from src.services.observability import observe_step

logger = logging.getLogger(__name__)


REQUIRED_EVENT_COUNT = 15
STORY_STATE_FILENAME = ".story_state.json"
MAX_GENERATION_RETRIES = 1


@dataclass(frozen=True)
class StoryEvent:
    """An event source selected for story generation."""

    path: str
    title: str
    time: str
    event_type: str
    content: str


@dataclass(frozen=True)
class GeneratedStory:
    """Parsed LLM story output."""

    title: str
    body: str


@dataclass(frozen=True)
class SavedStory:
    """Persisted story metadata."""

    story_id: str
    story_path: str
    event_paths: list[str]


class StoryGenerationError(Exception):
    """Base story generation error."""


class StoryOutputInvalidError(StoryGenerationError):
    """Raised when LLM output cannot be used as a story."""


class StoryStateSaveError(StoryGenerationError):
    """Raised when story file was saved but state failed to persist."""

    def __init__(self, message: str, story_path: str):
        super().__init__(message)
        self.story_path = story_path


class StoryGenerationAgent:
    """Lightweight agent for generating one story from 15 event documents."""

    def __init__(self, kb_path: str | Path, llm_service: LLMService):
        self.kb_path = Path(kb_path)
        self.llm_service = llm_service
        self.stories_dir = self.kb_path / "stories"
        self.state_path = self.stories_dir / STORY_STATE_FILENAME

    def load_unconsumed_events(self) -> list[StoryEvent]:
        """Scan event markdown files and return those not yet consumed."""
        consumed_paths = set(self._load_state().get("generated_event_paths", []))
        events = []

        events_root = self.kb_path / "events"
        if not events_root.exists():
            return []

        for event_file in sorted(events_root.rglob("*.md")):
            if event_file.name.startswith("."):
                continue
            rel_path = event_file.relative_to(self.kb_path).as_posix()
            if rel_path in consumed_paths:
                continue
            try:
                content = event_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Failed to read event file %s: %s", rel_path, e)
                continue

            events.append(
                StoryEvent(
                    path=rel_path,
                    title=self._extract_title(content) or event_file.stem,
                    time=self._extract_field(content, "时间"),
                    event_type=self._extract_field(content, "事件类型"),
                    content=content,
                )
            )

        return sorted(events, key=self._event_sort_key)

    def select_events(self, events: list[StoryEvent]) -> list[StoryEvent]:
        """Select the earliest required events for one story."""
        return events[:REQUIRED_EVENT_COUNT]

    async def generate_story(self, events: list[StoryEvent]) -> GeneratedStory:
        """Generate and parse a story, retrying once on invalid output."""
        last_error = ""
        for attempt in range(MAX_GENERATION_RETRIES + 1):
            with observe_step(
                "story_generation.generate",
                metadata={"attempt": attempt + 1, "event_count": len(events)},
            ):
                try:
                    result = await self.llm_service.invoke(
                        prompt=self._build_user_prompt(events),
                        system_prompt=self._build_system_prompt(),
                        trace_node="story_generation.generate",
                        trace_metadata={
                            "attempt": attempt + 1,
                            "event_count": len(events),
                            "event_paths": [event.path for event in events],
                        },
                    )
                except Exception as e:
                    result = LLMCallResult(success=False, error=str(e))

            try:
                return self._parse_story_result(result)
            except StoryOutputInvalidError as e:
                last_error = str(e)
                logger.warning("Story generation output invalid on attempt %s: %s", attempt + 1, e)

        raise StoryOutputInvalidError(last_error or "故事生成结果无效")

    def save_story_and_mark_consumed(self, story: GeneratedStory, events: list[StoryEvent]) -> SavedStory:
        """Save story markdown first, then persist consumed event paths."""
        self.stories_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone()
        story_id = f"story_{now.strftime('%Y%m%d_%H%M%S')}"
        story_rel_path = f"stories/{story_id}.md"
        story_abs_path = self.kb_path / story_rel_path
        event_paths = [event.path for event in events]

        content = self._build_story_markdown(
            title=story.title,
            body=story.body,
            generated_at=now.isoformat(),
            event_paths=event_paths,
        )
        story_abs_path.write_text(content, encoding="utf-8")

        try:
            self._mark_events_consumed(
                story_id=story_id,
                story_path=story_rel_path,
                event_paths=event_paths,
                created_at=now.isoformat(),
            )
        except Exception as e:
            raise StoryStateSaveError(
                f"故事已生成并保存，但事件消费状态保存失败: {e}",
                story_rel_path,
            ) from e

        return SavedStory(story_id=story_id, story_path=story_rel_path, event_paths=event_paths)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"generated_event_paths": [], "stories": []}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Story state file is invalid, rebuilding empty state: %s", self.state_path)
            return {"generated_event_paths": [], "stories": []}
        if not isinstance(data, dict):
            return {"generated_event_paths": [], "stories": []}
        generated = data.get("generated_event_paths")
        stories = data.get("stories")
        return {
            "generated_event_paths": generated if isinstance(generated, list) else [],
            "stories": stories if isinstance(stories, list) else [],
        }

    def _save_state(self, state: dict[str, Any]) -> None:
        self.stories_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.state_path)

    def _mark_events_consumed(
        self,
        story_id: str,
        story_path: str,
        event_paths: list[str],
        created_at: str,
    ) -> None:
        state = self._load_state()
        existing = list(dict.fromkeys(state.get("generated_event_paths", [])))
        for path in event_paths:
            if path not in existing:
                existing.append(path)

        stories = state.get("stories", [])
        stories.append({
            "story_id": story_id,
            "file_path": story_path,
            "event_paths": event_paths,
            "created_at": created_at,
        })

        self._save_state({
            "generated_event_paths": existing,
            "stories": stories,
            "updated_at": created_at,
        })

    def _build_system_prompt(self) -> str:
        return """你是一位擅长整理口述回忆的中文写作者。

请把给定的 15 个事件整理成一篇独立的故事，而不是传记章节、年表或资料清单。

要求：
- 使用第一人称“我”。
- 必须覆盖全部 15 个事件，可以详略不同，但不能完全漏掉任何一个。
- 只能依据事件材料写作；可以自然衔接和概括主题，但不要编造材料中没有的具体人物、地点、对白、心理活动或因果。
- 语言温暖、朴素、可读，像老人回忆往事。
- 不要在正文里列出来源文件路径。
- 只输出 JSON，不要输出 Markdown 代码块或额外解释。

JSON 格式：
{
  "title": "故事标题",
  "body": "故事正文"
}
"""

    def _build_user_prompt(self, events: list[StoryEvent]) -> str:
        blocks = []
        for index, event in enumerate(events, 1):
            blocks.append(
                "\n".join([
                    f"【事件 {index}】",
                    f"路径：{event.path}",
                    f"标题：{event.title}",
                    f"时间：{event.time or '未知'}",
                    f"类型：{event.event_type or 'other'}",
                    "原文：",
                    event.content.strip(),
                ])
            )
        return "请根据下面 15 个事件生成一篇故事：\n\n" + "\n\n---\n\n".join(blocks)

    def _parse_story_result(self, result: LLMCallResult) -> GeneratedStory:
        if not result.success:
            raise StoryOutputInvalidError(result.error or "LLM 调用失败")
        raw = (result.content or "").strip()
        if not raw:
            raise StoryOutputInvalidError("LLM 输出为空")

        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise StoryOutputInvalidError(f"无法解析故事 JSON: {e}") from e

        title = str(data.get("title") or "").strip()
        body = str(data.get("body") or "").strip()
        if not title:
            raise StoryOutputInvalidError("故事标题为空")
        if len(body) < 50:
            raise StoryOutputInvalidError("故事正文过短或为空")
        return GeneratedStory(title=title, body=body)

    def _build_story_markdown(
        self,
        title: str,
        body: str,
        generated_at: str,
        event_paths: list[str],
    ) -> str:
        source_lines = "\n".join(f"- {path}" for path in event_paths)
        return f"""# {title}

> 生成时间：{generated_at}
> 来源事件数：{len(event_paths)}

{body.strip()}

<!--
source_events:
{source_lines}
-->
"""

    def _event_sort_key(self, event: StoryEvent) -> tuple[int, int, str]:
        year = self._extract_year(event.time)
        if year is None:
            year = self._extract_year(event.content)
        return (0 if year is not None else 1, year or 9999, event.path)

    def _extract_year(self, value: str) -> int | None:
        match = re.search(r"\d{4}", value or "")
        return int(match.group(0)) if match else None

    def _extract_title(self, content: str) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return ""

    def _extract_field(self, content: str, label: str) -> str:
        match = re.search(rf"- \*\*{re.escape(label)}\*\*[：:](.+)", content)
        return match.group(1).strip() if match else ""
