"""Global session manager — singleton that tracks active agents per user.

Enforces mutual exclusivity: only ONE agent can be active per user_id at any time.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel


class AgentType(str, Enum):
    """Types of agents that can be active."""
    INTERVIEW = "interview"
    KB_ORGANIZER = "kb_organizer"
    BIOGRAPHY_OUTLINE = "biography_outline"
    BIOGRAPHY_WRITING = "biography_writing"


class ActiveSession(BaseModel):
    """Represents an active agent session."""
    session_id: str
    user_id: str
    agent_type: AgentType
    started_at: datetime
    agent_instance: Any = None  # Holds the actual agent object (for interview)
    
    class Config:
        arbitrary_types_allowed = True


class SessionConflictError(Exception):
    """Raised when a user tries to start an agent while another is active."""
    def __init__(self, user_id: str, active_type: AgentType, session_id: str):
        self.user_id = user_id
        self.active_type = active_type
        self.session_id = session_id
        super().__init__(
            f"User {user_id} already has active agent: {active_type.value} (session: {session_id})"
        )


class SessionManager:
    """Singleton session manager.
    
    Thread-safe via asyncio.Lock. Tracks one active session per user_id.
    
    Rules:
    - acquire() raises SessionConflictError if a DIFFERENT agent type is active
    - For INTERVIEW: if same user calls acquire(INTERVIEW) again, returns existing session_id
    - release() removes the session, freeing the user for another agent
    """
    
    _instance: Optional["SessionManager"] = None
    _lock_cls = asyncio.Lock
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._sessions: Dict[str, ActiveSession] = {}  # user_id → ActiveSession
        self._lock = asyncio.Lock()
    
    @classmethod
    def get_instance(cls) -> "SessionManager":
        """Get the singleton instance."""
        return cls()
    
    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing only)."""
        cls._instance = None
    
    async def get_active_session(self, user_id: str) -> Optional[ActiveSession]:
        """Get the active session for a user, or None."""
        async with self._lock:
            return self._sessions.get(user_id)
    
    async def acquire(self, user_id: str, agent_type: AgentType) -> str:
        """Acquire a session slot for the user.
        
        Returns:
            session_id (str): New or existing session ID.
            
        Raises:
            SessionConflictError: If a different agent type is already active.
        """
        async with self._lock:
            existing = self._sessions.get(user_id)
            
            if existing is not None:
                # Same agent type for interview → return existing session
                if existing.agent_type == agent_type and agent_type == AgentType.INTERVIEW:
                    return existing.session_id
                # Same agent type for non-interview → conflict (task still running)
                if existing.agent_type == agent_type:
                    raise SessionConflictError(user_id, existing.agent_type, existing.session_id)
                # Different agent type → conflict
                raise SessionConflictError(user_id, existing.agent_type, existing.session_id)
            
            # Create new session
            session_id = self._generate_session_id()
            self._sessions[user_id] = ActiveSession(
                session_id=session_id,
                user_id=user_id,
                agent_type=agent_type,
                started_at=datetime.now(timezone.utc),
            )
            return session_id
    
    async def release(self, user_id: str, session_id: Optional[str] = None) -> bool:
        """Release a session slot.
        
        Args:
            user_id: The user whose session to release.
            session_id: Optional session_id for verification.
            
        Returns:
            True if released, False if no matching session found.
        """
        async with self._lock:
            existing = self._sessions.get(user_id)
            if existing is None:
                return False
            if session_id and existing.session_id != session_id:
                return False
            del self._sessions[user_id]
            return True
    
    async def get_interview_agent(self, user_id: str) -> Optional[Any]:
        """Get the stored interview agent instance for a user."""
        async with self._lock:
            session = self._sessions.get(user_id)
            if session and session.agent_type == AgentType.INTERVIEW:
                return session.agent_instance
            return None
    
    async def store_agent_instance(self, user_id: str, agent: Any) -> None:
        """Store an agent instance in the active session (for interview persistence)."""
        async with self._lock:
            session = self._sessions.get(user_id)
            if session:
                session.agent_instance = agent
    
    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        now = datetime.now()
        return f"sess_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
