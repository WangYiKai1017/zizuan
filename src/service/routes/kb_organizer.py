"""KB Organizer agent route handlers."""
import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from src.service.schemas.requests import UserIdRequest
from src.service.session_manager import SessionManager, AgentType, SessionConflictError
from src.service.sse_response import SSEEmitter
from src.service.agent_runners.kb_organizer_runner import KBOrganizerRunner
from src.services.observability import start_api_observation

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
    api_observation = start_api_observation(
        agent="kb_organizer",
        operation="run",
        route="POST /kb-organizer/run",
        user_id=request.user_id,
        input=request.model_dump(mode="json", exclude_none=True),
    )
    try:
        _validate_user_kb(request.user_id)
        session_manager = SessionManager.get_instance()
        session_id = await session_manager.acquire(request.user_id, AgentType.KB_ORGANIZER)
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
    runner = KBOrganizerRunner(
        user_id=request.user_id,
        session_id=session_id,
        emitter=emitter,
        trace_context=api_observation.child_context(operation="run"),
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


@router.get("/result/{user_id}")
async def get_organizer_result(user_id: str):
    """Get the most recent organization result for a user."""
    _validate_user_kb(user_id)

    kb_path = _get_kb_path(user_id)
    result_path = Path(kb_path) / ".kb_organizer_result.json"
    if result_path.exists():
        try:
            return JSONResponse(content=json.loads(result_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail={
                "error": {
                    "code": "RESULT_CORRUPTED",
                    "message": "知识库整理结果文件损坏",
                    "details": str(exc),
                }
            }) from exc

    return JSONResponse(content={
        "user_id": user_id,
        "status": "no_result",
        "message": "暂无整理结果记录。请先运行知识库整理任务。",
    })
