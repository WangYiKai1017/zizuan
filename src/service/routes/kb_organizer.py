"""KB Organizer agent route handlers."""
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from src.service.schemas.requests import UserIdRequest
from src.service.session_manager import SessionManager, AgentType, SessionConflictError
from src.service.sse_response import SSEEmitter
from src.service.agent_runners.kb_organizer_runner import KBOrganizerRunner

router = APIRouter(prefix="/kb-organizer", tags=["kb-organizer"])


def _get_kb_path(user_id: str) -> str:
    """Get knowledge base path for user."""
    project_root = Path(__file__).parent.parent.parent.parent
    return str(project_root / "knowledge_base" / user_id)


def _validate_user_kb(user_id: str) -> None:
    """Validate user KB exists."""
    kb_path = _get_kb_path(user_id)
    if not Path(kb_path).exists():
        raise HTTPException(status_code=404, detail={
            "error": {"code": "USER_NOT_FOUND", "message": f"用户 {user_id} 的知识库不存在", "details": None}
        })


@router.post("/run")
async def run_kb_organizer(request: UserIdRequest):
    """Start KB organization task. Returns SSE stream."""
    _validate_user_kb(request.user_id)

    session_manager = SessionManager.get_instance()

    try:
        session_id = await session_manager.acquire(request.user_id, AgentType.KB_ORGANIZER)
    except SessionConflictError as e:
        raise HTTPException(status_code=409, detail={
            "error": {"code": "TASK_ALREADY_RUNNING", "message": str(e), "details": None}
        })

    emitter = SSEEmitter()
    runner = KBOrganizerRunner(user_id=request.user_id, session_id=session_id, emitter=emitter)

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


@router.get("/result/{user_id}")
async def get_organizer_result(user_id: str):
    """Get the most recent organization result for a user."""
    _validate_user_kb(user_id)

    # For now, return a placeholder. Full implementation would read from persisted result.
    # The KB organizer doesn't persist results to a file yet — this returns basic info.
    kb_path = _get_kb_path(user_id)

    return JSONResponse(content={
        "user_id": user_id,
        "status": "no_result",
        "message": "暂无整理结果记录。请先运行知识库整理任务。",
    })
