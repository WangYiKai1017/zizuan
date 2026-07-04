"""Interview message route tests with real LLM selection."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agents.guided_initial_interview_controller import GUIDED_STATE_FILENAME
from src.agents.interview_agent import InterviewAgent
from src.agents.interview_session_agent import SessionPhase
from src.config.llm_config import LLMConfig
from src.service.routes.interview import router
from src.service.session_manager import AgentType
from src.services.llm_service import LLMService


_HAS_LLM_CREDENTIALS = bool(os.getenv("DEEPSEEK_URL") and os.getenv("DEEPSEEK_APIKEY"))


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _parse_sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    current_event: str | None = None
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal current_event, data_lines
        if current_event is None:
            data_lines = []
            return
        payload = json.loads("\n".join(data_lines)) if data_lines else {}
        events.append((current_event, payload))
        current_event = None
        data_lines = []

    for line in body.splitlines():
        if line.startswith("event: "):
            current_event = line[len("event: "):]
        elif line.startswith("data: "):
            data_lines.append(line[len("data: "):])
        elif line == "":
            flush()

    flush()
    return events


class _ActiveInterviewSession:
    def __init__(self, interview_agent: InterviewAgent) -> None:
        self.phase = SessionPhase.INTERVIEW
        self.interview_agent = interview_agent
        self.conversation_history = interview_agent.conversation_history

    async def handle_user_input(self, user_input: str, candidate_questions=None):
        result = await self.interview_agent.handle_input(
            user_input,
            candidate_questions=candidate_questions,
        )
        self.conversation_history = self.interview_agent.conversation_history
        return result


class _FakeSessionManager:
    def __init__(self, agent: _ActiveInterviewSession, session_id: str) -> None:
        self.agent = agent
        self.session = SimpleNamespace(
            session_id=session_id,
            agent_type=AgentType.INTERVIEW,
        )

    async def get_active_session(self, user_id: str):
        return self.session

    async def get_interview_agent(self, user_id: str):
        return self.agent


def _write_guided_state(tmp_path: Path, user_id: str) -> None:
    state_path = tmp_path / user_id / GUIDED_STATE_FILENAME
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "guided_completed": False,
                "current_question_id": "q017",
                "completed_question_ids": [f"q{i:03d}" for i in range(1, 17)],
                "current_question_followup_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.mark.skipif(not _HAS_LLM_CREDENTIALS, reason="LLM credentials not configured")
def test_message_route_can_select_candidate_question_in_guided_phase(monkeypatch, tmp_path: Path) -> None:
    user_id = "user123"
    session_id = "sess_guided_001"
    _write_guided_state(tmp_path, user_id)

    llm_service = LLMService(LLMConfig.from_env())
    interview_agent = InterviewAgent(
        user_id=user_id,
        llm_service=llm_service,
        knowledge_base_root=tmp_path,
        address_style="您",
        initial_history=[
            {
                "role": "assistant",
                "content": "青春时期，有没有一位老师对您影响最大？他做了什么或说了什么，让您记到现在？",
            }
        ],
    )

    async def fake_identify_key_information(user_input: str):
        return None

    interview_agent._identify_key_information = fake_identify_key_information
    session_agent = _ActiveInterviewSession(interview_agent)
    fake_session_manager = _FakeSessionManager(session_agent, session_id=session_id)

    monkeypatch.setattr(
        "src.service.routes.interview.SessionManager.get_instance",
        lambda: fake_session_manager,
    )
    monkeypatch.setattr(
        "src.service.agent_runners.interview_runner.SessionManager.get_instance",
        lambda: fake_session_manager,
    )

    response = _client().post(
        "/api/interview/message",
        json={
            "user_id": user_id,
            "session_id": session_id,
            "message": (
                "中学时语文老师对我影响最大。她有一次把我的作文拿到全年级读，"
                "我第一次觉得自己也能靠文字被别人看见。后来她还单独找我谈过一次，"
                "说我不该总把自己藏起来。"
            ),
            "candidate_questions": [
                {
                    "id": "cand_1",
                    "question": "那次语文老师单独找您谈话时，她具体说了什么？",
                }
            ],
        },
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    agent_events = [data for event, data in events if event == "agent_message"]
    assert len(agent_events) == 1
    assert agent_events[0]["question_source"] == "candidate_question"
    assert agent_events[0]["candidate_question_id"] == "cand_1"
    assert "语文老师" in agent_events[0]["message"]
