"""Base class for all agent runners."""
from abc import ABC, abstractmethod
from src.service.sse_response import SSEEmitter


class BaseAgentRunner(ABC):
    """Abstract base for agent runners that emit SSE events during execution."""

    def __init__(self, user_id: str, session_id: str, emitter: SSEEmitter):
        self.user_id = user_id
        self.session_id = session_id
        self.emitter = emitter

    @abstractmethod
    async def run(self) -> None:
        """Execute the agent, emitting SSE events through self.emitter."""
        ...
