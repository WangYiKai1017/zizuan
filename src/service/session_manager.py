"""Global session manager — singleton that tracks active agents per user.

Enforces mutual exclusivity between agents that write the same data domain.
Biography agents (outline/writing) run in a separate slot — they are mutually exclusive
with each other but NOT with exclusive agents (interview, kb_organizer, story_generation),
because biography agents only read events and never write them.

Story generation has its own slot. It may run with KB Organizer because their
filesystem commits are coordinated by UserKBLockManager, but it still conflicts
with interview and another story generation task.
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
    STORY_GENERATION = "story_generation"

    @property
    def is_biography(self) -> bool:
        """Biography agents only read events — they don't conflict with exclusive agents."""
        return self in (AgentType.BIOGRAPHY_OUTLINE, AgentType.BIOGRAPHY_WRITING)


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
    
    Thread-safe via asyncio.Lock. Tracks compatible active sessions per user_id.
    
    Rules:
    - Story generation and KB Organizer may run together for the same user
    - Interview conflicts with Story generation and KB Organizer
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
        self._sessions: Dict[str, ActiveSession] = {}  # user_id → exclusive ActiveSession
        self._story_sessions: Dict[str, ActiveSession] = {}  # user_id → story ActiveSession
        self._biography_sessions: Dict[str, ActiveSession] = {}  # user_id → biography ActiveSession
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
        """Get the active session for a user, or None.

        Checks exclusive, story, and biography session stores in that order.
        The exclusive session takes priority when compatible tasks overlap.
        """
        async with self._lock:
            exclusive = self._sessions.get(user_id)
            if exclusive is not None:
                return exclusive
            story = self._story_sessions.get(user_id)
            if story is not None:
                return story
            return self._biography_sessions.get(user_id)
    
    async def acquire(self, user_id: str, agent_type: AgentType) -> str:
        """Acquire a session slot for the user.

        Biography agents (outline/writing) use a separate slot — they are mutually
        exclusive with each other but NOT with exclusive agents (interview, etc.),
        because biography agents only read events.

        Returns:
            session_id (str): New or existing session ID.

        Raises:
            SessionConflictError: If a conflicting agent type is already active.
        """
        async with self._lock:
            session_id = self._generate_session_id()

            if agent_type.is_biography:
                # Biography slot: only conflicts with other biography agents
                existing_bio = self._biography_sessions.get(user_id)
                if existing_bio is not None:
                    raise SessionConflictError(user_id, existing_bio.agent_type, existing_bio.session_id)
                self._biography_sessions[user_id] = ActiveSession(
                    session_id=session_id,
                    user_id=user_id,
                    agent_type=agent_type,
                    started_at=datetime.now(timezone.utc),
                )
                return session_id

            if agent_type == AgentType.STORY_GENERATION:
                existing_story = self._story_sessions.get(user_id)
                if existing_story is not None:
                    raise SessionConflictError(
                        user_id,
                        existing_story.agent_type,
                        existing_story.session_id,
                    )

                existing = self._sessions.get(user_id)
                if existing is not None and existing.agent_type != AgentType.KB_ORGANIZER:
                    raise SessionConflictError(
                        user_id,
                        existing.agent_type,
                        existing.session_id,
                    )

                self._story_sessions[user_id] = ActiveSession(
                    session_id=session_id,
                    user_id=user_id,
                    agent_type=agent_type,
                    started_at=datetime.now(timezone.utc),
                )
                return session_id

            # Exclusive slot: conflicts with all other exclusive agents
            existing = self._sessions.get(user_id)
            if existing is not None:
                # Same agent type for interview → return existing session
                if existing.agent_type == agent_type and agent_type == AgentType.INTERVIEW:
                    return existing.session_id
                # Any other case → conflict
                raise SessionConflictError(user_id, existing.agent_type, existing.session_id)

            existing_story = self._story_sessions.get(user_id)
            if existing_story is not None and agent_type != AgentType.KB_ORGANIZER:
                raise SessionConflictError(
                    user_id,
                    existing_story.agent_type,
                    existing_story.session_id,
                )

            self._sessions[user_id] = ActiveSession(
                session_id=session_id,
                user_id=user_id,
                agent_type=agent_type,
                started_at=datetime.now(timezone.utc),
            )
            return session_id
    
    async def release(self, user_id: str, session_id: Optional[str] = None) -> bool:
        """Release a session slot.

        Checks both the exclusive and biography session stores.

        Args:
            user_id: The user whose session to release.
            session_id: Optional session_id for verification.

        Returns:
            True if released, False if no matching session found.
        """
        async with self._lock:
            # Try biography sessions first
            bio = self._biography_sessions.get(user_id)
            if bio is not None and (session_id is None or bio.session_id == session_id):
                del self._biography_sessions[user_id]
                return True

            story = self._story_sessions.get(user_id)
            if story is not None and (session_id is None or story.session_id == session_id):
                del self._story_sessions[user_id]
                return True

            # Try exclusive sessions
            existing = self._sessions.get(user_id)
            if existing is None:
                return False
            if session_id and existing.session_id != session_id:
                return False
            del self._sessions[user_id]
            return True

    async def force_release_all(self, user_id: str) -> int:
        """Force-release all sessions (exclusive + biography) for a user.

        Used when deleting a user to ensure no orphaned session state remains.

        Returns:
            Number of sessions released (0 to 3).
        """
        async with self._lock:
            count = 0
            if user_id in self._biography_sessions:
                del self._biography_sessions[user_id]
                count += 1
            if user_id in self._story_sessions:
                del self._story_sessions[user_id]
                count += 1
            if user_id in self._sessions:
                del self._sessions[user_id]
                count += 1
            return count
    
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
