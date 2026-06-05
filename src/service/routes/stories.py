"""Story generation route handlers."""

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

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


@router.post("/generate")
async def generate_story(request: UserIdRequest):
    """Generate one story from the earliest 15 unconsumed events."""
    api_observation = start_api_observation(
        agent="story_generation",
        operation="generate",
        route="POST /stories/generate",
        user_id=request.user_id,
        input={"user_id": request.user_id},
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
                output={
                    "status": status,
                    "events_emitted": emitter.emitted_count,
                    "events_sent": emitter.sent_count,
                },
            )

    return EventSourceResponse(generate())
