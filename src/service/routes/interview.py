"""Interview agent route handlers."""
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from src.service.schemas.requests import UserIdRequest, InterviewMessageRequest, InterviewEndRequest, ErrorResponse
from src.service.session_manager import SessionManager, AgentType, SessionConflictError
from src.service.sse_response import SSEEmitter
from src.service.agent_runners.interview_runner import InterviewRunner

router = APIRouter(prefix="/interview", tags=["interview"])


@router.post("/start")
async def start_interview(request: UserIdRequest):
    """Start a new interview session. Returns SSE stream."""
    session_manager = SessionManager.get_instance()

    try:
        session_id = await session_manager.acquire(request.user_id, AgentType.INTERVIEW)
    except SessionConflictError as e:
        raise HTTPException(status_code=409, detail={
            "error": {"code": "TASK_ALREADY_RUNNING", "message": str(e), "details": None}
        })

    emitter = SSEEmitter()
    runner = InterviewRunner(user_id=request.user_id, session_id=session_id, emitter=emitter)

    async def generate():
        try:
            await runner.start()
        except Exception as ex:
            await emitter.emit_error("AGENT_ERROR", str(ex), recoverable=False)
            await emitter.emit_done("启动失败")
        async for chunk in emitter.stream():
            yield chunk

    return EventSourceResponse(generate())


@router.post("/message")
async def send_message(request: InterviewMessageRequest):
    """Send a message in an existing interview session. Returns SSE stream."""
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

    emitter = SSEEmitter()
    runner = InterviewRunner(user_id=request.user_id, session_id=request.session_id, emitter=emitter)

    async def generate():
        try:
            candidate_questions = None
            if request.candidate_questions:
                candidate_questions = [
                    {"id": cq.id, "question": cq.question}
                    for cq in request.candidate_questions
                ]
            await runner.handle_message(request.message, candidate_questions=candidate_questions)
        except Exception as ex:
            await emitter.emit_error("AGENT_ERROR", str(ex), recoverable=False)
            await emitter.emit_done()
        async for chunk in emitter.stream():
            yield chunk

    return EventSourceResponse(generate())


@router.post("/end")
async def end_interview(request: InterviewEndRequest):
    """End an interview session. Returns JSON summary."""
    session_manager = SessionManager.get_instance()
    session = await session_manager.get_active_session(request.user_id)

    if not session or session.agent_type != AgentType.INTERVIEW:
        raise HTTPException(status_code=404, detail={
            "error": {"code": "SESSION_NOT_FOUND", "message": "会话不存在", "details": None}
        })

    emitter = SSEEmitter()  # Not used for streaming here, but needed by runner constructor
    runner = InterviewRunner(user_id=request.user_id, session_id=request.session_id, emitter=emitter)

    summary = await runner.end()
    return JSONResponse(content=summary)


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
