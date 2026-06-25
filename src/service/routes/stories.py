"""Story generation route handlers."""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from src.agents.story_generation_agent import (
    LIFE_STAGE_LABELS,
    LIFE_STAGE_ORDER,
    STORY_STATE_FILENAME,
)
from src.service.agent_runners.story_runner import StoryRunner
from src.service.schemas.requests import UserIdRequest
from src.service.session_manager import AgentType, SessionConflictError, SessionManager
from src.service.sse_response import SSEEmitter
from src.services.observability import start_api_observation

router = APIRouter(prefix="/stories", tags=["stories"])


def _get_kb_path(user_id: str) -> str:
    project_root = Path(__file__).parent.parent.parent.parent
    return str(project_root / "knowledge_base" / user_id)


def _validate_user_kb(user_id: str) -> None:
    kb_path = _get_kb_path(user_id)
    if not Path(kb_path).exists():
        raise HTTPException(status_code=404, detail={
            "error": {"code": "USER_NOT_FOUND", "message": f"用户 {user_id} 的知识库不存在", "details": None}
        })


def _validate_life_stage(life_stage: str) -> None:
    if life_stage not in LIFE_STAGE_ORDER:
        raise HTTPException(status_code=400, detail={
            "error": {
                "code": "INVALID_LIFE_STAGE",
                "message": f"life_stage 必须是: {', '.join(LIFE_STAGE_ORDER)}",
                "details": {"allowed_values": list(LIFE_STAGE_ORDER)},
            }
        })


def _load_story_state(stories_dir: Path) -> dict[str, Any]:
    state_path = stories_dir / STORY_STATE_FILENAME
    if not state_path.exists():
        return {"stories": []}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {"stories": []}
    return data if isinstance(data, dict) else {"stories": []}


def _extract_markdown_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def _extract_generated_at(content: str) -> str:
    match = re.search(r"^>\s*生成时间[：:]\s*(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _extract_source_event_paths(content: str) -> list[str]:
    match = re.search(r"source_events:\s*\n(?P<body>.*?)\n-->", content, re.DOTALL)
    if not match:
        return []
    paths = []
    for line in match.group("body").splitlines():
        line = line.strip()
        if line.startswith("- "):
            paths.append(line[2:].strip())
    return paths


def _infer_life_stage_from_story(story_id: str, content: str) -> str:
    for stage in LIFE_STAGE_ORDER:
        if story_id.startswith(f"{stage}_story_"):
            return stage

    stage_labels = {label: stage for stage, label in LIFE_STAGE_LABELS.items()}
    match = re.search(r"^>\s*来源时期[：:]\s*(.+)$", content, re.MULTILINE)
    if match:
        return stage_labels.get(match.group(1).strip(), "")
    return ""


def _story_sort_key(story: dict[str, Any]) -> tuple[str, str]:
    return (story.get("created_at") or story.get("last_modified") or "", story.get("story_path") or "")


def _list_stories_for_stage(kb_path: Path, life_stage: str) -> list[dict[str, Any]]:
    stories_dir = kb_path / "stories"
    if not stories_dir.exists():
        return []

    state = _load_story_state(stories_dir)
    state_by_path = {}
    for item in state.get("stories", []):
        if not isinstance(item, dict):
            continue
        file_path = item.get("file_path") or item.get("story_path")
        if isinstance(file_path, str):
            state_by_path[file_path] = item

    stories = []
    for story_file in sorted(stories_dir.glob("*.md")):
        rel_path = story_file.relative_to(kb_path).as_posix()
        state_item = state_by_path.get(rel_path, {})
        try:
            content = story_file.read_text(encoding="utf-8")
        except Exception:
            continue

        story_id = str(state_item.get("story_id") or story_file.stem)
        story_stage = str(state_item.get("life_stage") or _infer_life_stage_from_story(story_id, content))
        if story_stage != life_stage:
            continue

        stat = story_file.stat()
        last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        generated_at = _extract_generated_at(content)
        event_paths = state_item.get("event_paths")
        if not isinstance(event_paths, list):
            event_paths = _extract_source_event_paths(content)

        stories.append({
            "story_id": story_id,
            "story_path": rel_path,
            "title": _extract_markdown_title(content, story_file.stem),
            "content": content,
            "life_stage": story_stage,
            "life_stage_label": LIFE_STAGE_LABELS.get(story_stage, story_stage),
            "created_at": str(state_item.get("created_at") or generated_at or last_modified),
            "source_event_count": len(event_paths),
            "event_paths": event_paths,
            "image_path": str(state_item.get("image_path") or ""),
            "illustration_paths": list(state_item.get("illustration_paths") or []),
            "size": stat.st_size,
            "last_modified": last_modified,
        })

    return sorted(stories, key=_story_sort_key, reverse=True)


@router.get("/{user_id}")
async def list_stories(
    user_id: str,
    life_stage: str = Query(..., description="人生阶段：childhood/youth/middle_age/elderly"),
):
    """List saved stories for a user and life stage."""
    _validate_user_kb(user_id)
    _validate_life_stage(life_stage)

    stories = _list_stories_for_stage(Path(_get_kb_path(user_id)), life_stage)
    return JSONResponse(content={
        "user_id": user_id,
        "life_stage": life_stage,
        "life_stage_label": LIFE_STAGE_LABELS.get(life_stage, life_stage),
        "count": len(stories),
        "stories": stories,
    })


@router.post("/generate")
async def generate_story(request: UserIdRequest):
    """Generate stories for all life stages with at least 15 unconsumed events."""
    api_observation = start_api_observation(
        agent="story_generation",
        operation="generate",
        route="POST /stories/generate",
        user_id=request.user_id,
        input=request.model_dump(mode="json", exclude_none=True),
    )
    try:
        _validate_user_kb(request.user_id)
        session_manager = SessionManager.get_instance()
        session_id = await session_manager.acquire(request.user_id, AgentType.STORY_GENERATION)
    except SessionConflictError as e:
        api_observation.end(status="failed", error=e)
        raise HTTPException(status_code=409, detail={
            "error": {"code": "TASK_ALREADY_RUNNING", "message": str(e), "details": None}
        })
    except Exception as ex:
        api_observation.end(status="failed", error=ex)
        raise

    api_observation.set_session_id(session_id)
    emitter = SSEEmitter()
    runner = StoryRunner(
        user_id=request.user_id,
        session_id=session_id,
        emitter=emitter,
        trace_context=api_observation.child_context(operation="generate"),
    )

    async def generate():
        status = "completed"
        error = None
        try:
            try:
                await runner.run()
            except Exception as ex:
                status = "failed"
                error = ex
                await emitter.emit_error("AGENT_ERROR", str(ex), recoverable=False)
                await emitter.emit_done("任务失败")
            finally:
                await session_manager.release(request.user_id, session_id)
            async for chunk in emitter.stream():
                yield chunk
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception as ex:
            status = "failed"
            error = ex
            raise
        finally:
            api_observation.end(
                status=status,
                error=error,
                output=emitter.trace_output(status),
            )

    return EventSourceResponse(generate())
