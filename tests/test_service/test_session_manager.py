"""Unit tests for SessionManager — mutual exclusivity logic."""
import asyncio
import pytest

from src.service.session_manager import SessionManager, AgentType, SessionConflictError


@pytest.fixture(autouse=True)
def reset_session_manager():
    """Reset singleton before each test."""
    SessionManager.reset()
    yield
    SessionManager.reset()


@pytest.mark.asyncio
async def test_acquire_creates_session():
    """Test that acquire creates a new session and returns session_id."""
    sm = SessionManager.get_instance()
    session_id = await sm.acquire("user001", AgentType.INTERVIEW)
    assert session_id.startswith("sess_")
    
    session = await sm.get_active_session("user001")
    assert session is not None
    assert session.user_id == "user001"
    assert session.agent_type == AgentType.INTERVIEW


@pytest.mark.asyncio
async def test_acquire_same_interview_returns_existing():
    """Test that re-acquiring INTERVIEW for same user returns same session."""
    sm = SessionManager.get_instance()
    session_id_1 = await sm.acquire("user001", AgentType.INTERVIEW)
    session_id_2 = await sm.acquire("user001", AgentType.INTERVIEW)
    assert session_id_1 == session_id_2


@pytest.mark.asyncio
async def test_acquire_different_agent_type_raises_conflict():
    """Test that acquiring a different agent type raises SessionConflictError."""
    sm = SessionManager.get_instance()
    await sm.acquire("user001", AgentType.INTERVIEW)
    
    with pytest.raises(SessionConflictError) as exc_info:
        await sm.acquire("user001", AgentType.KB_ORGANIZER)
    
    assert exc_info.value.user_id == "user001"
    assert exc_info.value.active_type == AgentType.INTERVIEW


@pytest.mark.asyncio
async def test_acquire_same_non_interview_type_raises_conflict():
    """Test that re-acquiring same non-interview type raises conflict (task still running)."""
    sm = SessionManager.get_instance()
    await sm.acquire("user001", AgentType.KB_ORGANIZER)
    
    with pytest.raises(SessionConflictError):
        await sm.acquire("user001", AgentType.KB_ORGANIZER)


@pytest.mark.asyncio
async def test_release_frees_slot():
    """Test that release allows a new agent to be acquired."""
    sm = SessionManager.get_instance()
    session_id = await sm.acquire("user001", AgentType.INTERVIEW)
    
    released = await sm.release("user001", session_id)
    assert released is True
    
    # Now can acquire a different type
    session_id_2 = await sm.acquire("user001", AgentType.KB_ORGANIZER)
    assert session_id_2 != session_id


@pytest.mark.asyncio
async def test_release_wrong_session_id_fails():
    """Test that release with wrong session_id returns False."""
    sm = SessionManager.get_instance()
    await sm.acquire("user001", AgentType.INTERVIEW)
    
    released = await sm.release("user001", "wrong_session_id")
    assert released is False


@pytest.mark.asyncio
async def test_release_nonexistent_user():
    """Test release for a user with no active session."""
    sm = SessionManager.get_instance()
    released = await sm.release("nonexistent_user")
    assert released is False


@pytest.mark.asyncio
async def test_different_users_independent():
    """Test that different users can run different agents simultaneously."""
    sm = SessionManager.get_instance()
    sid1 = await sm.acquire("user001", AgentType.INTERVIEW)
    sid2 = await sm.acquire("user002", AgentType.KB_ORGANIZER)
    sid3 = await sm.acquire("user003", AgentType.BIOGRAPHY_WRITING)
    
    assert sid1 != sid2 != sid3
    
    s1 = await sm.get_active_session("user001")
    s2 = await sm.get_active_session("user002")
    s3 = await sm.get_active_session("user003")
    
    assert s1.agent_type == AgentType.INTERVIEW
    assert s2.agent_type == AgentType.KB_ORGANIZER
    assert s3.agent_type == AgentType.BIOGRAPHY_WRITING


@pytest.mark.asyncio
async def test_store_and_get_interview_agent():
    """Test storing and retrieving an interview agent instance."""
    sm = SessionManager.get_instance()
    await sm.acquire("user001", AgentType.INTERVIEW)
    
    # Store a mock agent
    mock_agent = {"type": "mock_interview_agent"}
    await sm.store_agent_instance("user001", mock_agent)
    
    retrieved = await sm.get_interview_agent("user001")
    assert retrieved == mock_agent


@pytest.mark.asyncio
async def test_get_interview_agent_wrong_type():
    """Test that get_interview_agent returns None for non-interview sessions."""
    sm = SessionManager.get_instance()
    await sm.acquire("user001", AgentType.KB_ORGANIZER)
    
    result = await sm.get_interview_agent("user001")
    assert result is None
