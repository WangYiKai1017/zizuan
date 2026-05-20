"""Biography Outline agent route handlers."""
import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from src.service.schemas.requests import UserIdRequest, ChapterConfirmRequest
from src.service.session_manager import SessionManager, AgentType, SessionConflictError
from src.service.sse_response import SSEEmitter
from src.service.agent_runners.outline_runner import OutlineRunner

router = APIRouter(prefix="/biography/outline", tags=["biography-outline"])


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


@router.post("/generate")
async def generate_outline(request: UserIdRequest):
    """Generate or update biography outline. Returns SSE stream."""
    _validate_user_kb(request.user_id)

    session_manager = SessionManager.get_instance()

    try:
        session_id = await session_manager.acquire(request.user_id, AgentType.BIOGRAPHY_OUTLINE)
    except SessionConflictError as e:
        raise HTTPException(status_code=409, detail={
            "error": {"code": "TASK_ALREADY_RUNNING", "message": str(e), "details": None}
        })

    emitter = SSEEmitter()
    runner = OutlineRunner(user_id=request.user_id, session_id=session_id, emitter=emitter)

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


@router.get("/{user_id}")
async def get_outline(user_id: str):
    """Get current saved outline."""
    _validate_user_kb(user_id)

    from src.services.biography_file_manager import BiographyFileManager

    kb_path = _get_kb_path(user_id)
    fm = BiographyFileManager(kb_path)
    outline = fm.load_outline()

    if not outline:
        raise HTTPException(status_code=404, detail={
            "error": {"code": "FILE_NOT_FOUND", "message": "大纲尚未生成", "details": None}
        })

    return JSONResponse(content=outline.model_dump(mode="json"))


@router.put("/{user_id}/chapters/{chapter_id}/confirm")
async def confirm_chapter(user_id: str, chapter_id: str, request: ChapterConfirmRequest = None):
    """Confirm a draft chapter for writing."""
    _validate_user_kb(user_id)

    from src.services.biography_file_manager import BiographyFileManager
    from src.models.biography_models import ChapterStatus

    kb_path = _get_kb_path(user_id)
    fm = BiographyFileManager(kb_path)
    outline = fm.load_outline()

    if not outline:
        raise HTTPException(status_code=404, detail={
            "error": {"code": "FILE_NOT_FOUND", "message": "大纲尚未生成", "details": None}
        })

    # Find chapter
    target_chapter = None
    for ch in outline.chapters:
        if ch.id == chapter_id:
            target_chapter = ch
            break

    if not target_chapter:
        raise HTTPException(status_code=404, detail={
            "error": {"code": "FILE_NOT_FOUND", "message": f"章节 {chapter_id} 不存在", "details": None}
        })

    # Validate status transition
    if target_chapter.status != ChapterStatus.DRAFT:
        raise HTTPException(status_code=400, detail={
            "error": {
                "code": "INVALID_STATUS_TRANSITION",
                "message": f"章节 {chapter_id} 当前状态为 {target_chapter.status.value}，无法确认",
                "details": None
            }
        })

    # Update status
    target_chapter.status = ChapterStatus.CONFIRMED
    target_chapter.confirmed_at = datetime.now()
    fm.save_outline(outline)

    return JSONResponse(content={
        "chapter_id": chapter_id,
        "status": "confirmed",
        "confirmed_at": target_chapter.confirmed_at.isoformat(),
        "message": "章节已确认，可进行写作",
    })
