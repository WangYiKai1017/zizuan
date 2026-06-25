"""Biography Writing agent route handlers."""
import asyncio
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from src.service.schemas.requests import UserIdRequest
from src.service.session_manager import SessionManager, AgentType, SessionConflictError
from src.service.sse_response import SSEEmitter
from src.service.agent_runners.writing_runner import WritingRunner
from src.services.observability import start_api_observation

router = APIRouter(prefix="/biography/writing", tags=["biography-writing"])


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
async def run_writing(request: UserIdRequest):
    """Start biography writing task. Returns SSE stream."""
    api_observation = start_api_observation(
        agent="biography_writing",
        operation="run",
        route="POST /biography/writing/run",
        user_id=request.user_id,
        input=request.model_dump(mode="json", exclude_none=True),
    )
    try:
        _validate_user_kb(request.user_id)
        session_manager = SessionManager.get_instance()
        session_id = await session_manager.acquire(request.user_id, AgentType.BIOGRAPHY_WRITING)
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
    runner = WritingRunner(
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


@router.get("/{user_id}/chapters")
async def get_chapters(user_id: str):
    """List all written chapter files."""
    _validate_user_kb(user_id)

    kb_path = _get_kb_path(user_id)
    chapters_dir = Path(kb_path) / "biography" / "chapters"

    if not chapters_dir.exists():
        return JSONResponse(content={
            "user_id": user_id,
            "chapters": [],
            "total_word_count": 0,
        })

    chapters = []
    total_words = 0
    for f in sorted(chapters_dir.iterdir()):
        if f.is_file() and f.suffix == ".md":
            size = f.stat().st_size
            total_words += size
            # Extract chapter_id and title from filename (e.g., "ch01_故乡的记忆.md")
            stem = f.stem
            parts = stem.split("_", 1)
            chapter_id = parts[0] if parts else stem
            title = parts[1] if len(parts) > 1 else stem

            chapters.append({
                "chapter_id": chapter_id,
                "title": title,
                "file_path": f"biography/chapters/{f.name}",
                "word_count": size,
                "written_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })

    return JSONResponse(content={
        "user_id": user_id,
        "chapters": chapters,
        "total_word_count": total_words,
    })


@router.get("/{user_id}/full")
async def get_full_biography(user_id: str):
    """Get the merged full biography."""
    _validate_user_kb(user_id)

    kb_path = _get_kb_path(user_id)
    full_bio_path = Path(kb_path) / "biography" / "full_biography.md"

    if not full_bio_path.exists():
        raise HTTPException(status_code=404, detail={
            "error": {"code": "FILE_NOT_FOUND", "message": "完整传记尚未生成", "details": None}
        })

    content = full_bio_path.read_text(encoding="utf-8")

    # Try to get outline for metadata
    from src.services.biography_file_manager import BiographyFileManager
    fm = BiographyFileManager(kb_path)
    outline = fm.load_outline()

    return JSONResponse(content={
        "user_id": user_id,
        "title": outline.title if outline else "未命名",
        "author": outline.author if outline else "未知",
        "total_word_count": len(content),
        "chapters_count": content.count("## "),
        "generated_at": datetime.fromtimestamp(full_bio_path.stat().st_mtime).isoformat(),
        "content": content,
    })
