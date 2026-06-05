"""Base class for all agent runners."""
from abc import ABC, abstractmethod
from src.service.sse_response import SSEEmitter
from src.services.observability import ObservabilityContext


class BaseAgentRunner(ABC):
    """Abstract base for agent runners that emit SSE events during execution."""

    def __init__(
        self,
        user_id: str,
        session_id: str,
        emitter: SSEEmitter,
        trace_context: ObservabilityContext | None = None,
    ):
        self.user_id = user_id
        self.session_id = session_id
        self.emitter = emitter
        self.trace_context = trace_context

    def build_trace_context(self, *, agent: str, operation: str, phase: str | None = None) -> ObservabilityContext:
        if self.trace_context is not None:
            return ObservabilityContext(
                agent=agent,
                operation=operation,
                user_id=self.user_id,
                session_id=self.session_id,
                phase=phase,
                trace_id=self.trace_context.trace_id,
                parent_observation_id=self.trace_context.parent_observation_id,
                tags=self.trace_context.tags,
                metadata=dict(self.trace_context.metadata),
            )
        return ObservabilityContext(
            agent=agent,
            operation=operation,
            user_id=self.user_id,
            session_id=self.session_id,
            phase=phase,
        )

    @abstractmethod
    async def run(self) -> None:
        """Execute the agent, emitting SSE events through self.emitter."""
        ...
