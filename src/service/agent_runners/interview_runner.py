"""Interview agent runner — wraps InterviewSessionAgent for SSE streaming."""
from typing import Optional, List, Dict

from src.service.sse_response import SSEEmitter
from src.service.session_manager import SessionManager
from src.agents.interview_session_agent import InterviewSessionAgent
from src.services.llm_service import get_llm_service
from src.services.observability import ObservabilityContext, observability_context


class InterviewRunner:
    """Manages interview sessions with SSE event emission."""

    def __init__(self, user_id: str, session_id: str, emitter: SSEEmitter):
        self.user_id = user_id
        self.session_id = session_id
        self.emitter = emitter

    async def start(self) -> None:
        """Start a new interview session. Emits session_started + agent_message."""
        with observability_context(ObservabilityContext(
            agent="interview",
            operation="start",
            user_id=self.user_id,
            session_id=self.session_id,
        )):
            # Create InterviewSessionAgent
            llm_service = get_llm_service()
            agent = InterviewSessionAgent(user_id=self.user_id, llm_service=llm_service)

            # Store in SessionManager
            session_manager = SessionManager.get_instance()
            await session_manager.store_agent_instance(self.user_id, agent)

            # Get opening message
            opening = await agent.start()

        # Emit events
        await self.emitter.emit("session_started", {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "phase": agent.phase.value if hasattr(agent.phase, 'value') else str(agent.phase),
        })
        await self.emitter.emit("agent_message", {
            "session_id": self.session_id,
            "message": opening,
            "phase": agent.phase.value if hasattr(agent.phase, 'value') else str(agent.phase),
        })
        await self.emitter.emit_done("会话已建立")

    async def handle_message(
        self,
        message: str,
        candidate_questions: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        """Handle a user message. Emits agent_message (+ optional phase_changed)."""
        session_manager = SessionManager.get_instance()
        agent = await session_manager.get_interview_agent(self.user_id)

        if agent is None:
            await self.emitter.emit_error("SESSION_NOT_FOUND", "会话不存在或已过期", recoverable=False)
            await self.emitter.emit_done()
            return

        # Track phase before handling
        phase_before = agent.phase

        with observability_context(ObservabilityContext(
            agent="interview",
            operation="message",
            user_id=self.user_id,
            session_id=self.session_id,
            phase=phase_before.value if hasattr(phase_before, 'value') else str(phase_before),
        )):
            # Process message
            result = await agent.handle_user_input(message, candidate_questions=candidate_questions)

        phase_after = agent.phase

        # Emit phase change if applicable
        if phase_before != phase_after:
            await self.emitter.emit("phase_changed", {
                "session_id": self.session_id,
                "from_phase": phase_before.value if hasattr(phase_before, 'value') else str(phase_before),
                "to_phase": phase_after.value if hasattr(phase_after, 'value') else str(phase_after),
            })

        # Emit agent message
        await self.emitter.emit("agent_message", {
            "session_id": self.session_id,
            "message": result.question,
            "phase": phase_after.value if hasattr(phase_after, 'value') else str(phase_after),
            "question_source": result.source,
            "candidate_question_id": result.candidate_question_id,
        })
        await self.emitter.emit_done()

    async def end(self) -> dict:
        """End the session. Returns summary dict (not SSE)."""
        session_manager = SessionManager.get_instance()
        agent = await session_manager.get_interview_agent(self.user_id)

        ending_message = ""
        archived = False
        if agent is not None:
            with observability_context(ObservabilityContext(
                agent="interview",
                operation="end",
                user_id=self.user_id,
                session_id=self.session_id,
                phase=agent.phase.value if hasattr(agent.phase, 'value') else str(agent.phase),
            )):
                ending_message = await agent.end_session()
            archived = True
            phase_reached = agent.phase.value if hasattr(agent.phase, 'value') else str(agent.phase)
            total_turns = len(getattr(agent, 'conversation_history', []) or [])
        else:
            phase_reached = "unknown"
            total_turns = 0

        # Release session
        await session_manager.release(self.user_id, self.session_id)

        # Build summary
        summary = {
            "status": "ended",
            "session_id": self.session_id,
            "summary": {
                "total_turns": total_turns,
                "phase_reached": phase_reached,
                "archived": archived,
            },
            "ending_message": ending_message,
        }
        return summary
