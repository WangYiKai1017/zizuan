"""Interview agent route handlers."""
import asyncio
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from src.service.schemas.requests import (
    UserIdRequest,
    InterviewMessageRequest,
    InterviewEndRequest,
    InterviewProfilePrefillRequest,
    ErrorResponse,
)
from src.service.session_manager import SessionManager, AgentType, SessionConflictError
from src.service.sse_response import SSEEmitter
from src.service.agent_runners.interview_runner import InterviewRunner
from src.services.observability import start_api_observation
from src.storage.markdown_file_manager import MarkdownFileManager

router = APIRouter(prefix="/interview", tags=["interview"])


REQUIRED_PROFILE_FIELDS = [
    "name",
    "age",
    "occupation",
    "family_status",
    "living_arrangement",
]


def _knowledge_base_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent / "knowledge_base"


def _normalize_gender(gender: str | None) -> str | None:
    if not gender:
        return None
    normalized = gender.strip().lower()
    male_values = {"男", "男性", "male", "m", "man"}
    female_values = {"女", "女性", "female", "f", "woman"}
    if normalized in male_values:
        return "男"
    if normalized in female_values:
        return "女"
    return gender.strip()


def _extract_birth_year(birth_date: str | None) -> str | None:
    if not birth_date:
        return None
    match = re.search(r"(19|20)\d{2}", birth_date)
    return match.group(0) if match else None


def _missing_required_profile_fields(profile_info: dict) -> list[str]:
    return [
        field
        for field in REQUIRED_PROFILE_FIELDS
        if not profile_info.get(field)
    ]


def _read_user_profile(file_manager: MarkdownFileManager) -> dict:
    user_md_path = file_manager.base_path / "user.md"
    if not user_md_path.exists():
        return {}

    key_map = {
        "微信ID": "wechat_id",
        "姓名": "name",
        "年龄": "age",
        "性别": "gender",
        "出生日期": "birth_date",
        "出生年份": "birth_year",
        "职业": "occupation",
        "家庭状况": "family_status",
        "居住情况": "living_arrangement",
    }
    profile = {}
    line_pattern = re.compile(r"^- (.+?):\s*(.+)$")
    for line in user_md_path.read_text(encoding="utf-8").splitlines():
        match = line_pattern.match(line.strip())
        if not match:
            continue
        label, value = match.group(1).strip(), match.group(2).strip()
        if label in key_map:
            profile[key_map[label]] = value
    return profile


@router.post("/profile/prefill")
async def prefill_interview_profile(request: InterviewProfilePrefillRequest):
    """Store WeChat-provided profile fields before starting a new interview."""
    user_id = request.user_id
    profile_info = {
        "wechat_id": request.wechat_id,
        "name": request.name,
        "age": request.age,
        "birth_date": request.birth_date,
        "birth_year": _extract_birth_year(request.birth_date),
        "gender": _normalize_gender(request.gender),
    }
    profile_info = {
        key: value
        for key, value in profile_info.items()
        if value is not None and value != ""
    }

    file_manager = MarkdownFileManager(
        base_path=str(_knowledge_base_root()),
        conversation_id=user_id,
    )
    profile_path = file_manager.create_or_update_user_md(profile_info)
    summary_index_path = file_manager.create_or_update_summary_index()

    stored_profile = _read_user_profile(file_manager)
    missing_required = _missing_required_profile_fields(stored_profile)
    return JSONResponse(content={
        "status": "ok",
        "user_id": user_id,
        "wechat_id": request.wechat_id,
        "profile": stored_profile,
        "profile_path": profile_path,
        "summary_index_path": summary_index_path,
        "profile_complete": not missing_required,
        "missing_required_fields": missing_required,
    })


@router.post("/start")
async def start_interview(request: UserIdRequest):
    """Start a new interview session. Returns SSE stream."""
    api_observation = start_api_observation(
        agent="interview",
        operation="start",
        route="POST /interview/start",
        user_id=request.user_id,
        input={"user_id": request.user_id},
    )
    try:
        session_manager = SessionManager.get_instance()
        session_id = await session_manager.acquire(request.user_id, AgentType.INTERVIEW)
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
    runner = InterviewRunner(
        user_id=request.user_id,
        session_id=session_id,
        emitter=emitter,
        trace_context=api_observation.child_context(operation="start"),
    )

    async def generate():
        status = "completed"
        error = None
        try:
            try:
                await runner.start()
            except Exception as ex:
                status = "failed"
                error = ex
                await emitter.emit_error("AGENT_ERROR", str(ex), recoverable=False)
                await emitter.emit_done("启动失败")
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


@router.post("/message")
async def send_message(request: InterviewMessageRequest):
    """Send a message in an existing interview session. Returns SSE stream."""
    api_observation = start_api_observation(
        agent="interview",
        operation="message",
        route="POST /interview/message",
        user_id=request.user_id,
        session_id=request.session_id,
        input={"user_id": request.user_id, "session_id": request.session_id},
    )
    try:
        session_manager = SessionManager.get_instance()
        session = await session_manager.get_active_session(request.user_id)

        if not session or session.agent_type != AgentType.INTERVIEW:
            raise HTTPException(status_code=404, detail={
                "error": {"code": "SESSION_NOT_FOUND", "message": "会话不存在", "details": None}
            })

        if session.session_id != request.session_id:
            raise HTTPException(status_code=404, detail={
                "error": {"code": "SESSION_NOT_FOUND", "message": "会话ID不匹配", "details": None}
            })

        api_observation.set_session_id(request.session_id)
        emitter = SSEEmitter()
        runner = InterviewRunner(
            user_id=request.user_id,
            session_id=request.session_id,
            emitter=emitter,
            trace_context=api_observation.child_context(operation="message"),
        )
    except Exception as ex:
        api_observation.end(status="failed", error=ex)
        raise

    async def generate():
        status = "completed"
        error = None
        try:
            try:
                candidate_questions = None
                if request.candidate_questions:
                    candidate_questions = [
                        {"id": cq.id, "question": cq.question}
                        for cq in request.candidate_questions
                    ]
                await runner.handle_message(request.message, candidate_questions=candidate_questions)
            except Exception as ex:
                status = "failed"
                error = ex
                await emitter.emit_error("AGENT_ERROR", str(ex), recoverable=False)
                await emitter.emit_done()
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


@router.post("/end")
async def end_interview(request: InterviewEndRequest):
    """End an interview session. Returns JSON summary."""
    api_observation = start_api_observation(
        agent="interview",
        operation="end",
        route="POST /interview/end",
        user_id=request.user_id,
        session_id=request.session_id,
        input={"user_id": request.user_id, "session_id": request.session_id},
    )
    try:
        session_manager = SessionManager.get_instance()
        session = await session_manager.get_active_session(request.user_id)

        if not session or session.agent_type != AgentType.INTERVIEW:
            raise HTTPException(status_code=404, detail={
                "error": {"code": "SESSION_NOT_FOUND", "message": "会话不存在", "details": None}
            })

        if session.session_id != request.session_id:
            raise HTTPException(status_code=404, detail={
                "error": {"code": "SESSION_NOT_FOUND", "message": "会话ID不匹配", "details": None}
            })

        api_observation.set_session_id(request.session_id)
        emitter = SSEEmitter()  # Not used for streaming here, but needed by runner constructor
        runner = InterviewRunner(
            user_id=request.user_id,
            session_id=request.session_id,
            emitter=emitter,
            trace_context=api_observation.child_context(operation="end"),
        )

        summary = await runner.end()
        api_observation.end(
            status="completed",
            output={
                "status": summary.get("status"),
                "session_id": summary.get("session_id"),
                "structured_archive": summary.get("structured_archive"),
            },
        )
        return JSONResponse(content=summary)
    except HTTPException as ex:
        api_observation.end(status="failed", error=ex)
        raise
    except Exception as ex:
        api_observation.end(status="failed", error=ex)
        raise


@router.get("/status/{user_id}/{session_id}")
async def get_interview_status(user_id: str, session_id: str):
    """Get current interview session status."""
    session_manager = SessionManager.get_instance()
    session = await session_manager.get_active_session(user_id)

    if not session or session.session_id != session_id:
        raise HTTPException(status_code=404, detail={
            "error": {"code": "SESSION_NOT_FOUND", "message": "会话不存在", "details": None}
        })

    agent = await session_manager.get_interview_agent(user_id)

    status_data = {
        "session_id": session.session_id,
        "user_id": user_id,
        "phase": agent.phase.value if agent and hasattr(agent.phase, 'value') else "unknown",
        "started_at": session.started_at.isoformat(),
    }

    # Add turn_count if available
    if agent and hasattr(agent, 'turn_count'):
        status_data["turn_count"] = agent.turn_count

    return JSONResponse(content=status_data)
