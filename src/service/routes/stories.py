"""Story generation route handlers."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.service.agent_runners.story_runner import StoryRunner
from src.service.schemas.requests import UserIdRequest
from src.service.session_manager import AgentType, SessionConflictError, SessionManager
from src.service.sse_response import SSEEmitter

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
    _validate_user_kb(request.user_id)

    session_manager = SessionManager.get_instance()
    try:
        session_id = await session_manager.acquire(request.user_id, AgentType.STORY_GENERATION)
    except SessionConflictError as e:
        raise HTTPException(status_code=409, detail={
            "error": {"code": "TASK_ALREADY_RUNNING", "message": str(e), "details": None}
        })

    emitter = SSEEmitter()
    runner = StoryRunner(user_id=request.user_id, session_id=session_id, emitter=emitter)

    async def generate():
        try:
            await runner.run()
        except Exception as ex:
            await emitter.emit_error("AGENT_ERROR", str(ex), recoverable=False)
            await emitter.emit_done("任务失败")
        finally:
            await session_manager.release(request.user_id, session_id)
        async for chunk in emitter.stream():
            yield chunk

    return EventSourceResponse(generate())
