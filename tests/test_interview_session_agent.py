"""Comprehensive tests for the refactored interview agent system.

Covers:
- InterviewSessionAgent: KB check, address style, user.md parsing,
  session end, session archive parsing, session resume
- InterviewAgent: topic tracking
- MarkdownFileManager: wiki link normalization, summary index, user.md, session archive
- MemoryCacheTool: fuzzy matching
"""

import pytest
import tempfile
import re
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.agents.interview_session_agent import InterviewSessionAgent, SessionPhase
from src.agents.interview_agent import InterviewAgent
from src.agents.guided_initial_interview_controller import (
    GUIDED_STATE_FILENAME,
    GuidedInitialInterviewController,
)
from src.agents.profile_collection_agent import ProfileCollectionAgent
from src.storage.markdown_file_manager import MarkdownFileManager
from src.tools.memory_cache_tool import MemoryCacheTool


# ============================================================
# Helpers / Fixtures
# ============================================================


def _make_session_agent(tmpdir: str, user_id: str = "test_user") -> InterviewSessionAgent:
    """Create an InterviewSessionAgent with mocked LLM and temp KB path."""
    mock_llm = MagicMock()
    mock_llm.invoke = AsyncMock(return_value=MagicMock(content="mock response"))

    mock_memory_manager = MagicMock()
    mock_memory_manager.repository = MagicMock()
    mock_memory_manager.repository.get_latest_conversation_records = AsyncMock(return_value=[])
    mock_memory_manager.repository.file_manager = MagicMock()

    agent = InterviewSessionAgent(
        user_id=user_id,
        llm_service=mock_llm,
        memory_manager=mock_memory_manager,
    )
    # Redirect KB paths to temp directory
    agent.knowledge_base_root = Path(tmpdir)
    agent.knowledge_base_path = Path(tmpdir) / user_id
    return agent


def _create_full_kb_structure(kb_path: Path) -> None:
    """Create a full KB directory structure under kb_path."""
    required_directories = [
        "events/childhood",
        "events/youth",
        "events/middle_age",
        "events/elderly",
        "people/family",
        "people/friends",
        "people/colleagues",
        "people/others",
        "timeline",
        "themes",
    ]
    for d in required_directories:
        (kb_path / d).mkdir(parents=True, exist_ok=True)

    # index.md
    (kb_path / "index.md").write_text("# 记忆库索引", encoding="utf-8")


# ============================================================
# 1. test_check_knowledge_base
# ============================================================


class TestCheckKnowledgeBase:
    @pytest.mark.asyncio
    async def test_kb_not_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            assert await agent._check_knowledge_base() is False

    @pytest.mark.asyncio
    async def test_kb_existing_but_incomplete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            agent.knowledge_base_path.mkdir(parents=True)
            assert await agent._check_knowledge_base() is False

    @pytest.mark.asyncio
    async def test_kb_full_structure_but_only_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            _create_full_kb_structure(agent.knowledge_base_path)
            # Only index.md exists — should still be False
            assert await agent._check_knowledge_base() is False

    @pytest.mark.asyncio
    async def test_kb_full_structure_with_content_but_incomplete_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            _create_full_kb_structure(agent.knowledge_base_path)
            # Add an additional md file
            person_file = agent.knowledge_base_path / "people" / "family" / "mom.md"
            person_file.write_text("# 母亲", encoding="utf-8")
            assert await agent._check_knowledge_base() is False

    @pytest.mark.asyncio
    async def test_kb_full_structure_with_complete_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            _create_full_kb_structure(agent.knowledge_base_path)
            user_md = agent.knowledge_base_path / "user.md"
            user_md.write_text(
                "# 被采访者档案\n\n"
                "## 基本信息\n"
                "- 姓名: 张三\n"
                "- 年龄: 75\n"
                "- 职业: 退休工人\n"
                "- 家庭状况: 与妻子同住\n"
                "- 居住情况: 上海，与老伴同住\n",
                encoding="utf-8",
            )
            assert await agent._check_knowledge_base() is True


# ============================================================
# 2. test_compute_address_style
# ============================================================


class TestComputeAddressStyle:
    def _agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            return _make_session_agent(tmpdir)

    def test_elderly_male(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            profile = {"name": "张三", "age": "75", "family_status": "妻子已故"}
            assert agent._compute_address_style(profile) == "张爷爷"

    def test_elderly_female(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            profile = {"name": "李秀英", "age": "80", "family_status": "丈夫健在"}
            assert agent._compute_address_style(profile) == "李奶奶"

    def test_gender_from_wechat_profile_takes_priority(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            profile = {"name": "李秀英", "age": "80", "gender": "女"}
            assert agent._compute_address_style(profile) == "李奶奶"

    def test_middle_age_male(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            profile = {"name": "王强", "age": "55", "family_status": "妻子是教师"}
            assert agent._compute_address_style(profile) == "王叔叔"

    def test_middle_age_female(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            profile = {"name": "陈梅", "age": "60", "family_status": "老公退休了"}
            assert agent._compute_address_style(profile) == "陈阿姨"

    def test_young_male(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            profile = {"name": "刘伟", "age": "45", "family_status": "老婆在外地工作"}
            assert agent._compute_address_style(profile) == "刘先生"

    def test_young_female(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            profile = {"name": "赵敏", "age": "40", "family_status": "丈夫是工程师"}
            assert agent._compute_address_style(profile) == "赵女士"

    def test_unknown_gender_uses_neutral_address(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            profile = {"name": "王秀兰", "age": "78"}
            assert agent._compute_address_style(profile) == "您"

    def test_no_age(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            profile = {"name": "张三"}
            assert agent._compute_address_style(profile) == "您"

    def test_no_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            profile = {"age": "75"}
            assert agent._compute_address_style(profile) == "您"

    def test_invalid_age_string(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            profile = {"name": "张三", "age": "不知道"}
            assert agent._compute_address_style(profile) == "您"

    def test_empty_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            assert agent._compute_address_style({}) == "您"

    def test_none_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            assert agent._compute_address_style(None) == "您"


# ============================================================
# 3. test_parse_user_md
# ============================================================


class TestParseUserMd:
    def test_full_user_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir, user_id="u1")
            user_dir = Path(tmpdir) / "u1"
            user_dir.mkdir(parents=True)
            user_md = user_dir / "user.md"
            user_md.write_text(
                "# 被采访者档案\n\n"
                "## 基本信息\n"
                "- 微信ID: wx_openid_001\n"
                "- 姓名: 张三\n"
                "- 年龄: 75\n"
                "- 性别: 男\n"
                "- 出生日期: 1951-02-03\n"
                "- 出生年份: 1951\n"
                "- 职业: 退休教师\n"
                "- 家庭状况: 妻子健在\n"
                "- 居住情况: 与子女同住\n",
                encoding="utf-8",
            )
            result = agent._parse_user_md("u1")
            assert result["wechat_id"] == "wx_openid_001"
            assert result["name"] == "张三"
            assert result["age"] == "75"
            assert result["gender"] == "男"
            assert result["birth_date"] == "1951-02-03"
            assert result["birth_year"] == "1951"
            assert result["occupation"] == "退休教师"
            assert result["family_status"] == "妻子健在"
            assert result["living_arrangement"] == "与子女同住"

    def test_missing_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir, user_id="u2")
            user_dir = Path(tmpdir) / "u2"
            user_dir.mkdir(parents=True)
            user_md = user_dir / "user.md"
            user_md.write_text(
                "# 被采访者档案\n\n"
                "## 基本信息\n"
                "- 姓名: 王五\n"
                "- 年龄: 68\n",
                encoding="utf-8",
            )
            result = agent._parse_user_md("u2")
            assert result["name"] == "王五"
            assert result["age"] == "68"
            assert "occupation" not in result

    def test_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir, user_id="u3")
            result = agent._parse_user_md("u3")
            assert result == {}


class TestPrefilledProfileFlow:
    @pytest.mark.asyncio
    async def test_start_profile_collection_uses_prefilled_user_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir, user_id="prefill_user")
            _create_full_kb_structure(agent.knowledge_base_path)
            (agent.knowledge_base_path / "user.md").write_text(
                "# 被采访者档案\n\n"
                "## 基本信息\n"
                "- 微信ID: wx_openid_abc\n"
                "- 姓名: 王秀兰\n"
                "- 年龄: 78\n"
                "- 性别: 女\n"
                "- 出生日期: 1948-01-02\n"
                "- 出生年份: 1948\n",
                encoding="utf-8",
            )

            opening = await agent._start_profile_collection()

            assert "工作" in opening
            assert agent.phase == SessionPhase.PROFILE_COLLECTION
            assert agent.profile_agent.collected_info["name"] == "王秀兰"
            assert agent.profile_agent.collected_info["age"] == "78"
            assert agent.profile_agent.collected_info["gender"] == "女"
            assert "name" not in [
                field for field in ProfileCollectionAgent.REQUIRED_FIELDS
                if not agent.profile_agent.collected_info.get(field)
            ]

    @pytest.mark.asyncio
    async def test_complete_profile_starts_guided_interview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir, user_id="guided_user")
            _create_full_kb_structure(agent.knowledge_base_path)
            (agent.knowledge_base_path / "user.md").write_text(
                "# 被采访者档案\n\n"
                "## 基本信息\n"
                "- 姓名: 王秀兰\n"
                "- 年龄: 78\n"
                "- 性别: 女\n"
                "- 职业: 退休教师\n"
                "- 家庭状况: 与老伴同住\n"
                "- 居住情况: 上海，与老伴同住\n",
                encoding="utf-8",
            )
            agent.archive_tool = MagicMock()
            agent.archive_tool.create_user_knowledge_base = AsyncMock(return_value=None)
            agent.archive_tool.archive_conversation = AsyncMock(return_value=None)

            opening = await agent._start_profile_collection()

            assert agent.phase == SessionPhase.INTERVIEW
            assert "小时候住的房子" in opening
            assert (agent.knowledge_base_path / GUIDED_STATE_FILENAME).exists()


class TestGuidedInitialInterviewController:
    def _controller(self, tmpdir: str, llm_content=None) -> GuidedInitialInterviewController:
        mock_llm = MagicMock()
        mock_llm.invoke = AsyncMock(return_value=MagicMock(content=llm_content or {
            "question": "能再讲讲当时的细节吗？",
            "source": "generated",
            "candidate_question_id": None,
            "guided_question_completed": False,
            "move_to_next_guided_question": False,
        }))
        return GuidedInitialInterviewController(
            user_id="guided_user",
            llm_service=mock_llm,
            knowledge_base_root=Path(tmpdir),
        )

    def test_creates_initial_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = self._controller(tmpdir)

            state = controller.ensure_state()

            assert state["guided_completed"] is False
            assert state["current_question_id"] == "childhood_home"
            assert (Path(tmpdir) / "guided_user" / GUIDED_STATE_FILENAME).exists()

    def test_rebuilds_malformed_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "guided_user" / GUIDED_STATE_FILENAME
            state_path.parent.mkdir(parents=True)
            state_path.write_text("{broken", encoding="utf-8")
            controller = self._controller(tmpdir)

            state = controller.ensure_state()

            assert state["current_question_id"] == "childhood_home"

    @pytest.mark.asyncio
    async def test_candidate_question_source_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = self._controller(tmpdir, {
                "question": "您刚才提到父亲，那他对您影响最大的一件事是什么？",
                "source": "candidate_question",
                "candidate_question_id": "debug_q_1",
                "guided_question_completed": False,
                "move_to_next_guided_question": False,
            })

            decision = await controller.generate_next(
                user_input="父亲常带我去码头。",
                candidate_questions=[{"id": "debug_q_1", "question": "父亲对您影响最大的事情是什么？"}],
            )

            assert decision.result.source == "candidate_question"
            assert decision.result.candidate_question_id == "debug_q_1"

    @pytest.mark.asyncio
    async def test_moves_to_next_question_when_completed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = self._controller(tmpdir, {
                "question": "这个画面很清楚了。那您父母小时候是什么性格？",
                "source": "generated",
                "candidate_question_id": None,
                "guided_question_completed": True,
                "move_to_next_guided_question": True,
            })

            await controller.generate_next(user_input="我家老屋窗外有一棵大树。")
            state = controller.load_state()

            assert "childhood_home" in state["completed_question_ids"]
            assert state["current_question_id"] == "childhood_parents"

    @pytest.mark.asyncio
    async def test_does_not_advance_after_one_followup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = self._controller(tmpdir, {
                "question": "您能再讲讲当时学吉他的细节吗？",
                "source": "generated",
                "candidate_question_id": None,
                "guided_question_completed": False,
                "move_to_next_guided_question": False,
            })
            state = controller.ensure_state()
            state["current_question_followup_count"] = 1
            controller.save_state(state)

            decision = await controller.generate_next(user_input="想不起来了。")
            state = controller.load_state()

            assert "childhood_home" not in state["completed_question_ids"]
            assert state["current_question_id"] == "childhood_home"
            assert state["current_question_followup_count"] == 2
            assert "学吉他" in decision.result.question

    @pytest.mark.asyncio
    async def test_advances_after_two_followups(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = self._controller(tmpdir)
            state = controller.ensure_state()
            state["current_question_followup_count"] = 2
            controller.save_state(state)
            observation = MagicMock()
            captured = {}

            @contextmanager
            def fake_observe_step(node, **kwargs):
                captured["node"] = node
                captured["kwargs"] = kwargs
                yield observation

            with patch("src.agents.guided_initial_interview_controller.observe_step", fake_observe_step):
                decision = await controller.generate_next(user_input="想不起来了。")
            state = controller.load_state()

            assert "childhood_home" in state["completed_question_ids"]
            assert state["current_question_id"] == "childhood_parents"
            assert "父母" in decision.result.question
            assert captured["node"] == "guided.advance_to_next_question"
            assert captured["kwargs"]["metadata"]["reason"] == "max_followups_reached"
            observation.update.assert_called_once()


# ============================================================
# 4. test_end_session
# ============================================================


class TestEndSession:
    @pytest.mark.asyncio
    async def test_end_session_calls_start_ending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            agent.phase = SessionPhase.INTERVIEW

            # Mock interview agent
            mock_interview = MagicMock()
            mock_interview.generate_ending = AsyncMock(
                return_value={"message": "再见", "next_questions": [], "summary": "摘要"}
            )
            mock_interview.current_topic = "童年"
            mock_interview.topic_history = ["家庭"]
            mock_interview.session_summary = "本次摘要"
            agent.interview_agent = mock_interview

            # Mock archive_tool
            agent.archive_tool = MagicMock()
            agent.archive_tool.create_session_archive = AsyncMock(return_value="")
            agent.archive_tool.archive_conversation = AsyncMock(return_value=None)

            # Mock cache_tool
            agent.cache_tool = MagicMock()
            agent.cache_tool.get_cache = MagicMock(return_value=None)

            result = await agent.end_session()
            assert "再见" in result
            assert agent.phase == SessionPhase.CLOSED

    @pytest.mark.asyncio
    async def test_end_session_when_already_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            agent.phase = SessionPhase.CLOSED
            result = await agent.end_session()
            assert result == "会话已关闭"


# ============================================================
# 5. test_parse_session_archive
# ============================================================


class TestParseSessionArchive:
    def test_full_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            archive_file = Path(tmpdir) / "session_2026-06-01.md"
            archive_file.write_text(
                "# 采访记录\n\n"
                "## 本次采访摘要\n"
                "今天聊了童年故事\n\n"
                "## 下次采访建议问题\n"
                "1. 您小时候最喜欢玩什么？\n"
                "2. 上学的路怎么走？\n"
                "3. 放学后做什么？\n\n"
                "## 未完成的话题\n"
                "- 学校生活\n"
                "- 邻居关系\n\n"
                "## 采访上下文\n"
                "- 当前话题方向: 童年记忆\n"
                "- 情绪状态: 平静\n"
                "- 已探索话题: 家庭背景、出生地\n",
                encoding="utf-8",
            )
            result = agent._parse_session_archive(archive_file)
            assert result["next_questions"] == [
                "您小时候最喜欢玩什么？",
                "上学的路怎么走？",
                "放学后做什么？",
            ]
            assert result["unfinished_topics"] == ["学校生活", "邻居关系"]
            assert result["current_topic"] == "童年记忆"
            assert result["topic_history"] == ["家庭背景", "出生地"]
            assert "童年故事" in result["summary"]

    def test_incomplete_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            archive_file = Path(tmpdir) / "session_partial.md"
            archive_file.write_text(
                "# 采访记录\n\n"
                "## 本次采访摘要\n"
                "简短摘要\n",
                encoding="utf-8",
            )
            result = agent._parse_session_archive(archive_file)
            assert result["summary"] == "简短摘要"
            assert result["next_questions"] == []
            assert result["unfinished_topics"] == []
            assert result["current_topic"] is None
            assert result["topic_history"] == []

    def test_empty_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            archive_file = Path(tmpdir) / "session_empty.md"
            archive_file.write_text("", encoding="utf-8")
            result = agent._parse_session_archive(archive_file)
            assert result["next_questions"] == []
            assert result["summary"] == ""

    def test_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = _make_session_agent(tmpdir)
            result = agent._parse_session_archive(Path(tmpdir) / "nope.md")
            assert result["next_questions"] == []
            assert result["summary"] == ""


# ============================================================
# 6. test_resume_session_loads_context
# ============================================================


class TestResumeSession:
    @pytest.mark.asyncio
    async def test_resume_loads_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            user_id = "resume_user"
            agent = _make_session_agent(tmpdir, user_id=user_id)

            # Create KB structure with user.md
            kb_path = Path(tmpdir) / user_id
            _create_full_kb_structure(kb_path)
            user_md = kb_path / "user.md"
            user_md.write_text(
                "# 被采访者档案\n\n"
                "## 基本信息\n"
                "- 姓名: 刘大爷\n"
                "- 年龄: 78\n"
                "- 家庭状况: 妻子健在\n",
                encoding="utf-8",
            )

            # Create session archive
            sessions_dir = kb_path / "sessions"
            sessions_dir.mkdir(parents=True)
            archive = sessions_dir / "session_2026-05-30_10-00.md"
            archive.write_text(
                "# 采访记录\n\n"
                "## 本次采访摘要\n"
                "聊了些往事\n\n"
                "## 下次采访建议问题\n"
                "1. 您当年在哪里上学？\n"
                "2. 小时候家里几口人？\n\n"
                "## 采访上下文\n"
                "- 当前话题方向: 童年\n"
                "- 已探索话题: 家庭、工作\n",
                encoding="utf-8",
            )

            # Mock LLM to return something
            agent.llm_service.invoke = AsyncMock(
                return_value=MagicMock(content="欢迎回来")
            )

            # Mock query_tool
            agent.query_tool = MagicMock()
            agent.query_tool.query = AsyncMock(return_value="一些知识库内容")

            # Call resume
            result = await agent._resume_session()

            # Verify address style computed
            assert agent.address_style == "刘爷爷"

            # Verify candidate questions loaded
            assert agent.initial_candidate_questions is not None
            assert len(agent.initial_candidate_questions) == 2

            # Verify interview agent created with topic history
            assert agent.interview_agent is not None
            assert agent.interview_agent.topic_history == ["家庭", "工作"]
            assert agent.interview_agent.current_topic == "童年"


# ============================================================
# 7. test_topic_tracking (InterviewAgent)
# ============================================================


class TestTopicTracking:
    def _make_interview_agent(self) -> InterviewAgent:
        mock_llm = MagicMock()
        mock_llm.invoke = AsyncMock(return_value=MagicMock(content="{}"))
        mock_mm = MagicMock()
        mock_cache = MagicMock()
        mock_query = MagicMock()
        mock_archive = MagicMock()

        return InterviewAgent(
            user_id="topic_test",
            llm_service=mock_llm,
            memory_manager=mock_mm,
            cache_tool=mock_cache,
            query_tool=mock_query,
            archive_tool=mock_archive,
        )

    def test_detect_topic_from_events(self):
        agent = self._make_interview_agent()
        key_info = {"events": ["当兵经历"], "persons": [], "locations": []}
        result = agent._detect_current_topic(key_info)
        assert result == "当兵经历"

    def test_detect_topic_from_persons(self):
        agent = self._make_interview_agent()
        key_info = {"events": [], "persons": ["母亲"], "locations": []}
        result = agent._detect_current_topic(key_info)
        assert result == "母亲"

    def test_detect_topic_none_when_empty(self):
        agent = self._make_interview_agent()
        assert agent._detect_current_topic(None) is None
        assert agent._detect_current_topic({}) is None

    def test_topic_turn_count_increments_same_topic(self):
        agent = self._make_interview_agent()
        agent.current_topic = "童年"
        agent.topic_turn_count = 3

        # Simulate same topic detected
        detected = "童年"
        if detected == agent.current_topic:
            agent.topic_turn_count += 1

        assert agent.topic_turn_count == 4

    def test_topic_turn_count_resets_on_new_topic(self):
        agent = self._make_interview_agent()
        agent.current_topic = "童年"
        agent.topic_turn_count = 5

        # Simulate new topic detected
        detected = "工作经历"
        if detected != agent.current_topic:
            agent.topic_history.append(agent.current_topic)
            agent.current_topic = detected
            agent.topic_turn_count = 1

        assert agent.current_topic == "工作经历"
        assert agent.topic_turn_count == 1
        assert "童年" in agent.topic_history

    def test_should_switch_when_count_exceeds_max(self):
        agent = self._make_interview_agent()
        agent.current_topic = "家庭"
        agent.topic_turn_count = 8

        should_switch = agent.topic_turn_count >= agent.topic_max_turns
        assert should_switch is True

    def test_should_not_switch_under_max(self):
        agent = self._make_interview_agent()
        agent.topic_turn_count = 5
        should_switch = agent.topic_turn_count >= agent.topic_max_turns
        assert should_switch is False


# ============================================================
# 8. test_wiki_link_normalization (MarkdownFileManager)
# ============================================================


class TestWikiLinkNormalization:
    def _make_fm(self, tmpdir: str) -> MarkdownFileManager:
        return MarkdownFileManager(base_path=tmpdir, conversation_id="user001")

    def test_absolute_path_to_relative(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = self._make_fm(tmpdir)
            result = fm._normalize_wiki_link(
                f"{tmpdir}/user001/events/childhood/play.md"
            )
            assert result == "events/childhood/play.md"

    def test_already_relative_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = self._make_fm(tmpdir)
            result = fm._normalize_wiki_link("events/childhood/play.md")
            assert result == "events/childhood/play.md"

    def test_path_with_knowledge_base_prefix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = self._make_fm(tmpdir)
            result = fm._normalize_wiki_link("knowledge_base/user001/people/family/mom.md")
            assert result == "people/family/mom.md"

    def test_empty_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = self._make_fm(tmpdir)
            assert fm._normalize_wiki_link("") == ""
            assert fm._normalize_wiki_link(None) == ""

    def test_format_wiki_link_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = self._make_fm(tmpdir)
            result = fm.format_wiki_link("母亲", "people/family/mom.md")
            assert result == "[母亲](people/family/mom.md)"

    def test_format_wiki_link_with_absolute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = self._make_fm(tmpdir)
            result = fm.format_wiki_link(
                "童年",
                f"{tmpdir}/user001/events/childhood/play.md"
            )
            assert "events/childhood/play.md" in result
            assert result.startswith("[童年](")

    def test_directory_trailing_slash_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = self._make_fm(tmpdir)
            result = fm._normalize_wiki_link("events/childhood/")
            assert result == "events/childhood/"


# ============================================================
# 9. test_summary_index_generation
# ============================================================


class TestSummaryIndexGeneration:
    def test_generates_summary_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(base_path=tmpdir, conversation_id="idx_user")
            base = fm.base_path

            # Create some content files
            (base / "events" / "childhood" / "school.md").write_text(
                "# 小学回忆", encoding="utf-8"
            )
            (base / "people" / "family" / "father.md").write_text(
                "# 父亲", encoding="utf-8"
            )
            # Create user.md
            (base / "user.md").write_text("# 被采访者档案\n- 姓名: 测试", encoding="utf-8")

            path = fm.create_or_update_summary_index()
            content = Path(path).read_text(encoding="utf-8")

            assert "记忆库摘要目录" in content
            assert "school" in content
            assert "father" in content
            assert "被采访者档案" in content

    def test_excludes_biography_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(base_path=tmpdir, conversation_id="bio_test")
            base = fm.base_path

            # Create biography file (should be excluded)
            bio_dir = base / "events" / "childhood" / "biography"
            bio_dir.mkdir(parents=True, exist_ok=True)
            (bio_dir / "chapter1.md").write_text("# 传记第一章", encoding="utf-8")

            # Create normal file
            (base / "events" / "childhood" / "play.md").write_text(
                "# 玩耍", encoding="utf-8"
            )

            path = fm.create_or_update_summary_index()
            content = Path(path).read_text(encoding="utf-8")

            assert "play" in content
            assert "chapter1" not in content

    def test_empty_sections_not_included(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(base_path=tmpdir, conversation_id="empty_sec")
            # No content files created beyond what _ensure_directory_structure does
            path = fm.create_or_update_summary_index()
            content = Path(path).read_text(encoding="utf-8")
            # No "## 事件记录" because no md files in events subdirs
            assert "## 事件记录" not in content


# ============================================================
# 10. test_user_md_creation_and_update
# ============================================================


class TestUserMdCreationAndUpdate:
    def test_create_new_user_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(base_path=tmpdir, conversation_id="umd_user")
            profile = {
                "name": "张三",
                "age": "72",
                "gender": "男",
                "birth_date": "1954-05-06",
                "birth_year": "1954",
                "wechat_id": "wx_openid_001",
                "occupation": "退休工人",
            }
            path = fm.create_or_update_user_md(profile)
            content = Path(path).read_text(encoding="utf-8")

            assert "张三" in content
            assert "72" in content
            assert "男" in content
            assert "1954-05-06" in content
            assert "wx_openid_001" in content
            assert "退休工人" in content
            assert "被采访者档案" in content

    def test_update_existing_user_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(base_path=tmpdir, conversation_id="umd_user2")
            # First creation
            fm.create_or_update_user_md({"name": "李四", "age": "65"})
            # Update with new fields
            fm.create_or_update_user_md({"occupation": "医生", "age": "66"})
            content = (fm.base_path / "user.md").read_text(encoding="utf-8")

            assert "李四" in content
            assert "66" in content  # age updated
            assert "医生" in content  # new field added

    def test_missing_fields_dont_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(base_path=tmpdir, conversation_id="umd_user3")
            fm.create_or_update_user_md({"name": "王五", "age": "70", "occupation": "教师"})
            # Update without name — should not erase name
            fm.create_or_update_user_md({"age": "71"})
            content = (fm.base_path / "user.md").read_text(encoding="utf-8")

            assert "王五" in content
            assert "71" in content
            assert "教师" in content


# ============================================================
# 11. test_memory_cache_fuzzy_matching
# ============================================================


class TestMemoryCacheFuzzyMatching:
    def test_exact_tag_match_hit(self):
        cache = MemoryCacheTool()
        cache.append_cache("s1", "童年学校的故事", tags=["童年", "学校"])
        result = cache.get_cache("s1", {"tags": ["童年", "学校"], "query_text": ""})
        assert result is not None
        assert "童年学校" in result

    def test_keyword_substring_match_hit(self):
        cache = MemoryCacheTool()
        cache.append_cache("s2", "在工厂上班的经历很辛苦", tags=["工厂", "工作"])
        # Query with keyword that appears in content
        result = cache.get_cache("s2", "工厂上班")
        assert result is not None
        assert "工厂" in result

    def test_unrelated_query_miss(self):
        cache = MemoryCacheTool()
        cache.append_cache("s3", "童年学校的故事", tags=["童年", "学校"])
        result = cache.get_cache("s3", "火星探索计划xyz")
        assert result is None

    def test_clear_cache_empties(self):
        cache = MemoryCacheTool()
        cache.append_cache("s4", "some content", tags=["test"])
        cache.clear_cache("s4")
        result = cache.get_cache("s4", {"tags": ["test"], "query_text": ""})
        assert result is None

    def test_nonexistent_session_returns_none(self):
        cache = MemoryCacheTool()
        result = cache.get_cache("no_such_session", "anything")
        assert result is None


# ============================================================
# 12. test_session_archive_creation
# ============================================================


class TestSessionArchiveCreation:
    def test_creates_archive_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(base_path=tmpdir, conversation_id="archive_user")
            session_data = {
                "summary": "今天聊了家庭往事",
                "events": ["上学", "搬家"],
                "people": ["母亲", "父亲"],
                "timepoints": ["1960年"],
                "next_questions": ["您搬家后适应吗？", "新学校怎么样？"],
                "unfinished_topics": ["邻居关系"],
                "current_topic": "家庭",
                "emotion_state": "平静",
                "topic_history": ["童年", "学校"],
            }
            path = fm.create_session_archive(session_data)
            assert Path(path).exists()
            assert "sessions" in path

            content = Path(path).read_text(encoding="utf-8")
            assert "今天聊了家庭往事" in content
            assert "上学" in content
            assert "母亲" in content
            assert "1960年" in content
            assert "您搬家后适应吗？" in content
            assert "邻居关系" in content
            assert "当前话题方向: 家庭" in content
            assert "童年" in content

    def test_archive_with_empty_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(base_path=tmpdir, conversation_id="archive_empty")
            session_data = {
                "summary": "",
                "events": [],
                "people": [],
                "timepoints": [],
                "next_questions": [],
                "unfinished_topics": "",
                "current_topic": "",
                "emotion_state": "",
                "topic_history": [],
            }
            path = fm.create_session_archive(session_data)
            assert Path(path).exists()
            content = Path(path).read_text(encoding="utf-8")
            assert "采访记录" in content
            assert "（无）" in content

    def test_archive_correct_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(base_path=tmpdir, conversation_id="sec_check")
            session_data = {
                "summary": "摘要",
                "events": ["e1"],
                "people": ["p1"],
                "timepoints": [],
                "next_questions": ["q1"],
                "unfinished_topics": ["t1"],
                "current_topic": "topic",
                "emotion_state": "开心",
                "topic_history": ["prev"],
            }
            path = fm.create_session_archive(session_data)
            content = Path(path).read_text(encoding="utf-8")

            expected_sections = [
                "## 本次采访摘要",
                "## 收集的关键信息",
                "## 下次采访建议问题",
                "## 未完成的话题",
                "## 采访上下文",
            ]
            for section in expected_sections:
                assert section in content, f"Missing section: {section}"
