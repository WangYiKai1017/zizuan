"""Story generation agent.

Generate standalone first-person stories from life-stage groups of unconsumed
event files in a user's knowledge base.
"""

from __future__ import annotations

import hashlib
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
LIFE_STAGE_ORDER = ("childhood", "youth", "middle_age", "elderly")
LIFE_STAGE_LABELS = {
    "childhood": "童年时期",
    "youth": "青年时期",
    "middle_age": "中年时期",
    "elderly": "老年时期",
}


@dataclass(frozen=True)
class StoryEvent:
    """An event source selected for story generation."""

    path: str
    life_stage: str
    title: str
    time: str
    event_type: str
    content: str
    fingerprint: str


@dataclass(frozen=True)
class GeneratedStory:
    """Parsed LLM story output."""

    title: str
    body: str
    image_prompt: str = ""
    illustration_prompts: list[str] = None

    def __post_init__(self):
        if self.illustration_prompts is None:
            object.__setattr__(self, "illustration_prompts", [])


@dataclass(frozen=True)
class SavedStory:
    """Persisted story metadata."""

    story_id: str
    story_path: str
    life_stage: str
    event_paths: list[str]
    event_fingerprints: list[str] = None
    image_path: str = ""
    illustration_paths: list[str] = None

    def __post_init__(self):
        if self.event_fingerprints is None:
            object.__setattr__(self, "event_fingerprints", [])
        if self.illustration_paths is None:
            object.__setattr__(self, "illustration_paths", [])


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
    """Lightweight agent for generating stories from life-stage event groups."""

    def __init__(self, kb_path: str | Path, llm_service: LLMService, protagonist_gender: str = ""):
        self.kb_path = Path(kb_path)
        self.llm_service = llm_service
        self.stories_dir = self.kb_path / "stories"
        self.state_path = self.stories_dir / STORY_STATE_FILENAME
        self.protagonist_gender = protagonist_gender  # "male" | "female" | ""

    def load_unconsumed_events(self) -> list[StoryEvent]:
        """Scan event markdown files and return those not yet consumed."""
        state = self._load_state()
        consumed_paths = set(state.get("generated_event_paths", []))
        consumed_fingerprints = set(state.get("generated_event_fingerprints", []))
        uses_fingerprints = state.get("_fingerprint_state_present", True)
        events: list[StoryEvent] = []

        events_root = self.kb_path / "events"
        if not events_root.exists():
            return []

        for event_file in sorted(events_root.rglob("*.md")):
            if event_file.name.startswith("."):
                continue
            rel_path = event_file.relative_to(self.kb_path).as_posix()
            try:
                content = event_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Failed to read event file %s: %s", rel_path, e)
                continue

            fingerprint = self._event_fingerprint(content)
            events.append(
                StoryEvent(
                    path=rel_path,
                    life_stage=self._extract_life_stage(rel_path),
                    title=self._extract_title(content) or event_file.stem,
                    time=self._extract_field(content, "时间"),
                    event_type=self._extract_field(content, "事件类型"),
                    content=content,
                    fingerprint=fingerprint,
                )
            )

        if not uses_fingerprints:
            consumed_fingerprints.update(
                event.fingerprint
                for event in events
                if event.path in consumed_paths
            )
            state["generated_event_fingerprints"] = sorted(consumed_fingerprints)
            self._save_state(state)

        unconsumed = [
            event for event in events
            if event.fingerprint not in consumed_fingerprints
        ]
        return sorted(unconsumed, key=self._event_sort_key)

    def select_events(self, events: list[StoryEvent]) -> list[StoryEvent]:
        """Select the earliest required events for one story."""
        return events[:REQUIRED_EVENT_COUNT]

    def group_events_by_stage(self, events: list[StoryEvent]) -> dict[str, list[StoryEvent]]:
        """Group events by life stage from their file paths."""
        grouped: dict[str, list[StoryEvent]] = {stage: [] for stage in LIFE_STAGE_ORDER}
        for event in events:
            if event.life_stage in grouped:
                grouped[event.life_stage].append(event)
        return {
            stage: sorted(stage_events, key=self._event_sort_key)
            for stage, stage_events in grouped.items()
        }

    def select_ready_stage_events(
        self,
        events: list[StoryEvent],
    ) -> dict[str, list[StoryEvent]]:
        """Select at most one 15-event batch for each ready life stage."""
        grouped = self.group_events_by_stage(events)
        return {
            stage: self.select_events(stage_events)
            for stage, stage_events in grouped.items()
            if len(stage_events) >= REQUIRED_EVENT_COUNT
        }

    async def generate_story(
        self,
        events: list[StoryEvent],
        life_stage: str = "",
    ) -> GeneratedStory:
        """Generate and parse a story, retrying once on invalid output."""
        last_error = ""
        for attempt in range(MAX_GENERATION_RETRIES + 1):
            with observe_step(
                "story_generation.generate",
                metadata={
                    "attempt": attempt + 1,
                    "event_count": len(events),
                    "life_stage": life_stage,
                },
            ):
                try:
                    result = await self.llm_service.invoke(
                        prompt=self._build_user_prompt(events, life_stage),
                        system_prompt=self._build_system_prompt(life_stage),
                        trace_node="story_generation.generate",
                        trace_metadata={
                            "attempt": attempt + 1,
                            "event_count": len(events),
                            "life_stage": life_stage,
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

    def save_story_and_mark_consumed(
        self,
        story: GeneratedStory,
        events: list[StoryEvent],
        life_stage: str = "",
        image_path: str = "",
        illustration_paths: list[str] | None = None,
    ) -> SavedStory:
        """Save story markdown first, then persist consumed event paths."""
        self.stories_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone()
        stage_prefix = f"{life_stage}_" if life_stage else ""
        story_id = f"{stage_prefix}story_{now.strftime('%Y%m%d_%H%M%S')}"
        story_rel_path = f"stories/{story_id}.md"
        story_abs_path = self.kb_path / story_rel_path
        event_paths = [event.path for event in events]
        event_fingerprints = [event.fingerprint for event in events]
        illustration_paths = illustration_paths or []

        content = self._build_story_markdown(
            title=story.title,
            body=story.body,
            generated_at=now.isoformat(),
            life_stage=life_stage,
            event_paths=event_paths,
        )
        story_abs_path.write_text(content, encoding="utf-8")

        try:
            self._mark_events_consumed(
                story_id=story_id,
                story_path=story_rel_path,
                life_stage=life_stage,
                event_paths=event_paths,
                event_fingerprints=event_fingerprints,
                created_at=now.isoformat(),
                image_path=image_path,
                image_prompt=story.image_prompt,
                illustration_prompts=story.illustration_prompts,
                illustration_paths=illustration_paths,
            )
        except Exception as e:
            raise StoryStateSaveError(
                f"故事已生成并保存，但事件消费状态保存失败: {e}",
                story_rel_path,
            ) from e

        return SavedStory(
            story_id=story_id,
            story_path=story_rel_path,
            life_stage=life_stage,
            event_paths=event_paths,
            event_fingerprints=event_fingerprints,
            image_path=image_path,
            illustration_paths=illustration_paths,
        )

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "generated_event_paths": [],
                "generated_event_fingerprints": [],
                "stories": [],
                "_fingerprint_state_present": True,
            }
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Story state file is invalid, rebuilding empty state: %s", self.state_path)
            return {
                "generated_event_paths": [],
                "generated_event_fingerprints": [],
                "stories": [],
                "_fingerprint_state_present": True,
            }
        if not isinstance(data, dict):
            return {
                "generated_event_paths": [],
                "generated_event_fingerprints": [],
                "stories": [],
                "_fingerprint_state_present": True,
            }
        generated = data.get("generated_event_paths")
        generated_fingerprints = data.get("generated_event_fingerprints")
        stories = data.get("stories")
        return {
            "generated_event_paths": generated if isinstance(generated, list) else [],
            "generated_event_fingerprints": (
                generated_fingerprints
                if isinstance(generated_fingerprints, list)
                else []
            ),
            "stories": stories if isinstance(stories, list) else [],
            "_fingerprint_state_present": isinstance(generated_fingerprints, list),
        }

    def _save_state(self, state: dict[str, Any]) -> None:
        self.stories_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(".json.tmp")
        persisted_state = {
            key: value for key, value in state.items()
            if not key.startswith("_")
        }
        tmp_path.write_text(
            json.dumps(persisted_state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.state_path)

    def update_story_images(
        self,
        story_id: str,
        image_path: str,
        illustration_paths: list[str],
    ) -> None:
        """Update image_path and illustration_paths for an existing story in state."""
        state = self._load_state()
        stories = state.get("stories", [])
        for story in stories:
            if isinstance(story, dict) and story.get("story_id") == story_id:
                story["image_path"] = image_path
                story["illustration_paths"] = illustration_paths
                break
        self._save_state(state)

    def _mark_events_consumed(
        self,
        story_id: str,
        story_path: str,
        life_stage: str,
        event_paths: list[str],
        event_fingerprints: list[str],
        created_at: str,
        image_path: str = "",
        image_prompt: str = "",
        illustration_prompts: list[str] | None = None,
        illustration_paths: list[str] | None = None,
    ) -> None:
        state = self._load_state()
        existing = list(dict.fromkeys(state.get("generated_event_paths", [])))
        existing_fingerprints = list(dict.fromkeys(
            state.get("generated_event_fingerprints", [])
        ))

        if not state.get("_fingerprint_state_present", True):
            for path in existing:
                event_path = self.kb_path / path
                try:
                    content = event_path.read_text(encoding="utf-8")
                except OSError:
                    continue
                fingerprint = self._event_fingerprint(content)
                if fingerprint not in existing_fingerprints:
                    existing_fingerprints.append(fingerprint)

        for path in event_paths:
            if path not in existing:
                existing.append(path)
        for fingerprint in event_fingerprints:
            if fingerprint not in existing_fingerprints:
                existing_fingerprints.append(fingerprint)

        stories = state.get("stories", [])
        stories.append({
            "story_id": story_id,
            "file_path": story_path,
            "life_stage": life_stage,
            "event_paths": event_paths,
            "event_fingerprints": event_fingerprints,
            "created_at": created_at,
            "image_path": image_path,
            "image_prompt": image_prompt,
            "illustration_prompts": illustration_prompts or [],
            "illustration_paths": illustration_paths or [],
        })

        self._save_state({
            "generated_event_paths": existing,
            "generated_event_fingerprints": existing_fingerprints,
            "stories": stories,
            "updated_at": created_at,
        })

    @staticmethod
    def _event_fingerprint(content: str) -> str:
        """Return a path-independent identity for one exact event version."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _build_system_prompt(self, life_stage: str = "") -> str:
        stage_label = LIFE_STAGE_LABELS.get(life_stage, "同一人生时期")

        # Build protagonist description for image prompt constraints
        gender_label = ""
        if self.protagonist_gender == "male":
            gender_label = "Chinese man"
        elif self.protagonist_gender == "female":
            gender_label = "Chinese woman"
        else:
            gender_label = "Chinese person"

        return f"""你是一位擅长整理口述回忆的中文写作者。

请把给定的 15 个事件整理成一篇独立的故事，而不是传记章节、年表或资料清单。本次材料都来自{stage_label}，故事要围绕这个时期形成一个聚合主题，不要扩展成完整人生回顾。

要求：
- 使用第一人称"我"。
- 先理解这些事件共同呈现的主题，再组织成 4 到 7 个自然段落。
- 不要按年份逐条扩写，不要写成"一年一个事件"的流水账，不要每段都用年份开头。
- 不要求 15 个事件逐个显性展开；重要事件重点写，次要事件可以合并为背景、转折或变化。
- 不得忽略核心事件，但可以压缩、合并、概括次要事件。
- 只能依据事件材料写作；可以自然衔接和概括主题，但不要编造材料中没有的具体人物、地点、物件、对白、动作细节、心理活动或因果。
- 不要主动跳到其他人生阶段；结尾可以有短暂回望或总结，但不要引入材料外的新事件。
- 语言温暖、朴素、可读，像老人回忆往事。
- 不要在正文里列出来源文件路径。
- 只输出 JSON，不要输出 Markdown 代码块或额外解释。

JSON 格式：
{{{{
  "title": "故事标题",
  "body": "故事正文",
  "image_prompt": "English description for a cover illustration. The protagonist is a {gender_label} (age should match the story's life stage — could be a child, youth, adult, or elder depending on the events). Pencil sketch style, realistic shading, vintage newspaper illustration feel, warm nostalgic tone, soft textures. Describe the core scene or imagery of the story in under 100 words.",
  "illustration_prompts": "English description for a single 4-panel illustration arranged in a 2x2 grid. The protagonist is a {gender_label} (age should match the story's life stage — could be a child, youth, adult, or elder depending on the events). Each panel depicts a different key scene or emotional moment from the story. The protagonist is Chinese — do NOT depict people of other ethnicities as the main character. Pencil sketch style, realistic shading, vintage newspaper illustration feel, warm nostalgic tone, soft textures. Describe all four panels and their arrangement in under 120 words."
}}}}
"""

    def _build_user_prompt(
        self,
        events: list[StoryEvent],
        life_stage: str = "",
    ) -> str:
        stage_label = LIFE_STAGE_LABELS.get(life_stage, "同一人生时期")
        blocks = []
        for index, event in enumerate(events, 1):
            blocks.append(
                "\n".join([
                    f"【事件 {index}】",
                    f"路径：{event.path}",
                    f"时期：{LIFE_STAGE_LABELS.get(event.life_stage, event.life_stage or '未知')}",
                    f"标题：{event.title}",
                    f"时间：{event.time or '未知'}",
                    f"类型：{event.event_type or 'other'}",
                    "原文：",
                    event.content.strip(),
                ])
            )
        return f"请根据下面 15 个来自{stage_label}的事件生成一篇聚合故事：\n\n" + "\n\n---\n\n".join(blocks)

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
        image_prompt = str(data.get("image_prompt") or "").strip()
        raw_prompts = data.get("illustration_prompts") or []
        if isinstance(raw_prompts, str):
            raw_prompts = [raw_prompts]
        elif not isinstance(raw_prompts, list):
            raw_prompts = []
        illustration_prompts = [str(p).strip() for p in raw_prompts if isinstance(p, str) and p.strip()]
        if not title:
            raise StoryOutputInvalidError("故事标题为空")
        if len(body) < 50:
            raise StoryOutputInvalidError("故事正文过短或为空")
        return GeneratedStory(
            title=title,
            body=body,
            image_prompt=image_prompt,
            illustration_prompts=illustration_prompts,
        )

    def _build_story_markdown(
        self,
        title: str,
        body: str,
        generated_at: str,
        life_stage: str,
        event_paths: list[str],
    ) -> str:
        source_lines = "\n".join(f"- {path}" for path in event_paths)
        stage_line = f"> 来源时期：{LIFE_STAGE_LABELS.get(life_stage, life_stage)}\n" if life_stage else ""
        return f"""# {title}

> 生成时间：{generated_at}
{stage_line}> 来源事件数：{len(event_paths)}

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

    def _extract_life_stage(self, rel_path: str) -> str:
        parts = Path(rel_path).parts
        if len(parts) >= 3 and parts[0] == "events" and parts[1] in LIFE_STAGE_ORDER:
            return parts[1]
        return ""

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
