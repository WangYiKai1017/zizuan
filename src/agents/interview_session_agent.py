from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from pathlib import Path
import logging
import re

from src.agents.profile_collection_agent import ProfileCollectionAgent
from src.agents.interview_agent import InterviewAgent
from src.services.question_generator import QuestionResult
from src.services.llm_service import LLMService, get_llm_service
from src.services.memory_manager import MemoryManager
from src.services.knowledge_base_querier import KnowledgeBaseQuerier
from src.services.observability import observe_step
from src.models import SessionState, HandoffPackage
from src.tools import (
    MemoryCacheTool,
    KnowledgeQueryTool,
    MemoryArchiveTool
)
from src.storage.memory_repository import MemoryRepository
from src.storage.markdown_file_manager import MarkdownFileManager

logger = logging.getLogger(__name__)


class SessionPhase(Enum):
    """会话阶段"""
    INIT = "init"                    # 启动检查
    PROFILE_COLLECTION = "profile"   # 用户初始化
    INTERVIEW = "interview"          # 主体采访
    ENDING = "ending"                # 结束引导
    CLOSED = "closed"                # 会话关闭


class InterviewSessionAgent:
    """
    Agent服务主体
    
    职责：
    - 会话生命周期管理
    - 流程调度（初始化→采访→结束）
    - 知识库协调
    
    启动逻辑：
    1. 根据user_id检查知识库是否存在
    2. 存在 → 加载历史对话，进入采访流程
    3. 不存在 → 启动用户初始化流程
    
    会话结束由服务层显式调用 end_session() 触发。
    """
    
    def __init__(
        self,
        user_id: str,
        llm_service: LLMService = None,
        memory_manager: MemoryManager = None,
    ):
        self.user_id = user_id
        self.llm_service = llm_service or get_llm_service()
        
        # 知识库根目录（从项目根目录推导）
        self.knowledge_base_root = Path(__file__).resolve().parent.parent.parent / "knowledge_base"
        
        # 使用用户ID作为conversation_id，直接创建在知识库根目录下
        self.knowledge_base_path = self.knowledge_base_root / self.user_id
        logger.info(f"Using knowledge base path: {self.knowledge_base_path}")
        
        # 使用正确的用户目录初始化MemoryManager
        if memory_manager:
            self.memory_manager = memory_manager
        else:
            # 将用户ID作为conversation_id传递，确保使用指定ID而非随机ID
            file_manager = MarkdownFileManager(
                base_path=str(self.knowledge_base_root),
                conversation_id=self.user_id
            )
            self.memory_manager = MemoryManager(repository=MemoryRepository(file_manager=file_manager))
        
        # 会话状态
        self.phase = SessionPhase.INIT
        self.has_profile = False  # 是否完成了初始化
        self.address_style: str = "您"  # 对被采访者的称呼方式，默认为"您"
        
        # 子Agent
        self.profile_agent: Optional[ProfileCollectionAgent] = None
        self.interview_agent: Optional[InterviewAgent] = None
        
        # 工具集
        self.cache_tool = MemoryCacheTool()
        self.query_tool = KnowledgeQueryTool(
            querier=KnowledgeBaseQuerier(
                file_manager=MarkdownFileManager(
                    base_path=str(self.knowledge_base_root),
                    conversation_id=self.user_id
                ),
                llm_service=self.llm_service
            )
        )
        self.archive_tool = MemoryArchiveTool(self.memory_manager)
        
        # 会话状态和历史
        self.session_state: Optional[SessionState] = None
        self.conversation_history: list = []
        self.structured_archive_result: dict = {"status": "not_started", "error": None}
        self.current_round_queries: set = set()  # 本轮对话中已提出的查询请求

        # 老用户恢复会话时载入的候选问题（来自上一次 session 归档）
        self.initial_candidate_questions: Optional[List[Dict[str, str]]] = None
        self._candidates_passed: bool = False
        
    async def start(self) -> str:
        """
        启动会话
        
        Returns:
            开场白或欢迎语
        """
        # 检查知识库是否存在
        knowledge_base_exists = await self._check_knowledge_base()
        
        if knowledge_base_exists:
            # 老用户：加载历史，直接进入采访
            return await self._resume_session()
        else:
            # 新用户：启动初始化流程
            return await self._start_profile_collection()
    
    async def _check_knowledge_base(self) -> bool:
        """检查用户知识库是否存在且结构完整"""
        try:
            # 检查知识库目录是否存在
            if not self.knowledge_base_path.exists():
                logger.info(f"Knowledge base directory not found: {self.knowledge_base_path}")
                return False
            
            # 检查必要的目录结构是否完整
            required_directories = [
                "events",
                "events/childhood",
                "events/youth",
                "events/middle_age",
                "events/elderly",
                "people",
                "people/family",
                "people/friends",
                "people/colleagues",
                "people/others",
                "timeline",
                "themes"
            ]
            
            for dir_name in required_directories:
                dir_path = self.knowledge_base_path / dir_name
                if not dir_path.exists() or not dir_path.is_dir():
                    logger.info(f"Required directory missing or not a directory: {dir_path}")
                    return False
            
            profile_info = self._parse_user_md(self.user_id)
            if not self._is_profile_complete(profile_info):
                logger.info(f"Profile is incomplete for user: {self.user_id}")
                return False
            
            logger.info(f"Knowledge base structure is complete for user: {self.user_id}")
            return True
        except Exception as e:
            logger.error(f"Error checking knowledge base: {e}")
            return False
    
    async def _resume_session(self) -> str:
        """
        恢复会话（老用户）

        流程：
        1. 加载最近一次的 session 归档作为上下文
        2. 初始化 InterviewAgent 并生成欢迎回来的开场白
        """
        self.has_profile = True

        # 1. 查找并解析最新的 session 归档
        prev_context: dict = {}
        sessions_dir = self.knowledge_base_path / "sessions"
        if sessions_dir.exists() and sessions_dir.is_dir():
            session_files = sorted(sessions_dir.glob("session_*.md"), reverse=True)
            if session_files:
                latest_session = session_files[0]
                logger.info(f"Loading previous session archive: {latest_session}")
                prev_context = self._parse_session_archive(latest_session)
            else:
                logger.info(f"No session archive files found in {sessions_dir}")
        else:
            logger.info(f"Sessions directory not found: {sessions_dir}")

        # 2. 上次准备好的问题 → 转为候选问题格式，注入首轮 handle_input
        next_questions = prev_context.get("next_questions", []) or []
        if next_questions:
            self.initial_candidate_questions = [
                {"id": f"prev_q_{i}", "question": q}
                for i, q in enumerate(next_questions, 1)
            ]
            self._candidates_passed = False
            logger.info(f"Loaded {len(self.initial_candidate_questions)} candidate questions from previous session")

        # 3. 打包 resume 上下文（包含上次对话原文，避免重复发问）
        conversation_text = prev_context.get("conversation_text", "")
        resume_context = {
            "summary": prev_context.get("summary", ""),
            "unfinished_topics": prev_context.get("unfinished_topics", []),
            "current_topic": prev_context.get("current_topic"),
            "topic_history": prev_context.get("topic_history", []),
            "conversation_text": conversation_text,
        }

        # 4. 初始化 InterviewAgent 并启动
        self.interview_agent = InterviewAgent(
            user_id=self.user_id,
            llm_service=self.llm_service,
            memory_manager=self.memory_manager,
            cache_tool=self.cache_tool,
            query_tool=self.query_tool,
            archive_tool=self.archive_tool,
            knowledge_base_root=self.knowledge_base_root,
            resume_context=resume_context,
        )

        self.phase = SessionPhase.INTERVIEW
        return await self.interview_agent.start()

    def _parse_session_archive(self, file_path: Path) -> dict:
        """解析一次采访归档（session_*.md）以提取下次会话所需上下文。

        Returns dict with keys:
          - next_questions: List[str] — 上次为本次准备好的候选问题
          - unfinished_topics: List[str] — 上次未完成的话题
          - current_topic: Optional[str] — 上次结束时的当前话题方向
          - topic_history: List[str] — 已探索过的话题
          - summary: str — 上次采访摘要
        """
        result: dict = {
            "next_questions": [],
            "unfinished_topics": [],
            "current_topic": None,
            "topic_history": [],
            "summary": "",
        }

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read session archive {file_path}: {e}")
            return result

        if not content.strip():
            return result

        # 按二级标题分块
        sections: dict = {}
        current_heading: Optional[str] = None
        buffer: list = []
        for line in content.split("\n"):
            if line.startswith("## "):
                if current_heading is not None:
                    sections[current_heading] = "\n".join(buffer).strip()
                current_heading = line[3:].strip()
                buffer = []
            else:
                if current_heading is not None:
                    buffer.append(line)
        if current_heading is not None:
            sections[current_heading] = "\n".join(buffer).strip()

        # 下次采访建议问题
        questions_block = sections.get("下次采访建议问题", "")
        if questions_block:
            numbered_pattern = re.compile(r"^\s*\d+\.\s*(.+?)\s*$")
            for line in questions_block.split("\n"):
                match = numbered_pattern.match(line)
                if match:
                    q = match.group(1).strip()
                    if q:
                        result["next_questions"].append(q)

        # 未完成的话题
        unfinished_block = sections.get("未完成的话题", "")
        if unfinished_block:
            for line in unfinished_block.split("\n"):
                stripped = line.strip()
                if stripped.startswith("- "):
                    topic = stripped[2:].strip()
                    if topic:
                        result["unfinished_topics"].append(topic)

        # 采访上下文
        context_block = sections.get("采访上下文", "")
        if context_block:
            for line in context_block.split("\n"):
                stripped = line.strip()
                if not stripped.startswith("- "):
                    continue
                kv = stripped[2:]
                if ":" in kv:
                    key, value = kv.split(":", 1)
                elif "：" in kv:
                    key, value = kv.split("：", 1)
                else:
                    continue
                key = key.strip()
                value = value.strip()
                if key == "当前话题方向":
                    result["current_topic"] = value or None
                elif key == "已探索话题":
                    parts = re.split(r"[、,，]", value)
                    result["topic_history"] = [p.strip() for p in parts if p.strip()]

        # 本次采访摘要
        summary_block = sections.get("本次采访摘要", "")
        if summary_block:
            result["summary"] = summary_block.strip()

        # 本次对话记录（避免重启后 agent 围绕同一问题重复发问）
        conversation_block = sections.get("本次对话记录", "")
        if conversation_block:
            result["conversation_text"] = conversation_block.strip()

        return result
    
    async def _start_profile_collection(self) -> str:
        """
        启动用户初始化流程
        
        流程：
        1. 创建ProfileCollectionAgent
        2. 执行信息收集（仅在所有必填字段收集完成后结束）
        3. 收集完成后，生成基础知识库
        4. 将对话记录传递给采访流程
        """
        self.phase = SessionPhase.PROFILE_COLLECTION

        prefilled_profile = self._parse_user_md(self.user_id)

        # 从预填画像计算称呼方式，传给 ProfileCollectionAgent
        self.address_style = self._compute_address_style(prefilled_profile)
        logger.info(f"Computed address_style from prefilled profile: {self.address_style}")

        # 创建初始化Agent（不使用时间限制，仅依赖必填字段检查）
        self.profile_agent = ProfileCollectionAgent(
            user_id=self.user_id,
            llm_service=self.llm_service,
            memory_manager=self.memory_manager,
            max_duration_minutes=10**9,
            initial_info=prefilled_profile,
            address_style=self.address_style,
        )
        
        # 执行初始化流程
        welcome_message = await self.profile_agent.start()
        if self.profile_agent.is_completed:
            return await self._on_profile_complete()
        
        # 注意：初始化Agent会持续运行，直到所有必填字段收集完成
        # 完成后会触发 _on_profile_complete
        
        return welcome_message
    
    async def handle_user_input(
        self,
        user_input: str,
        candidate_questions: Optional[List[Dict[str, str]]] = None,
    ) -> QuestionResult:
        """
        处理用户输入

        根据当前阶段分发给对应的子Agent
        """
        if self.phase == SessionPhase.PROFILE_COLLECTION:
            return await self._handle_profile_input(user_input)
        elif self.phase == SessionPhase.INTERVIEW:
            return await self._handle_interview_input(user_input, candidate_questions)
        elif self.phase == SessionPhase.ENDING:
            return await self._handle_ending_input(user_input)
        else:
            return QuestionResult(
                question="会话已结束，期待下次再聊。",
                source="generated",
                candidate_question_id=None,
            )
    
    async def _handle_profile_input(self, user_input: str) -> QuestionResult:
        """处理初始化阶段的用户输入"""
        response = await self.profile_agent.handle_input(user_input)

        # 检查是否完成初始化
        if self.profile_agent.is_completed:
            response = await self._on_profile_complete()

        return QuestionResult(
            question=response,
            source="generated",
            candidate_question_id=None,
        )
    
    async def _on_profile_complete(self) -> str:
        """
        初始化完成后的处理
        
        流程：
        1. 获取所有对话记录
        2. 调用MemoryOrganizer生成基础知识库
        3. 将对话记录传递给采访流程
        4. 切换到采访阶段
        """
        # 1. 获取对话记录
        profile_history = self.profile_agent.get_conversation_history()
        self.conversation_history.extend(profile_history)
        
        # 2. 生成基础知识库
        with observe_step("profile.create_user_knowledge_base", as_type="tool"):
            await self.archive_tool.create_user_knowledge_base(
                user_id=self.user_id,
                conversation_history=profile_history,
                profile_info=self.profile_agent.collected_info
            )

        # 2.1 将当前内容归档
        with observe_step("profile.archive_conversation", as_type="tool"):
            await self.archive_tool.archive_conversation(
                user_id=self.user_id,
                conversation_history=profile_history,
                session_summary="用户初始化对话存档"
            )
        
        # 3. 标记已初始化
        self.has_profile = True

        # 3.1 根据收集到的画像信息计算称呼方式
        self.address_style = self._compute_address_style(self.profile_agent.collected_info or {})
        logger.info(f"Computed address_style after profile collection: {self.address_style}")

        # 4. 启动采访流程
        self.interview_agent = InterviewAgent(
            user_id=self.user_id,
            llm_service=self.llm_service,
            memory_manager=self.memory_manager,
            cache_tool=self.cache_tool,
            query_tool=self.query_tool,
            archive_tool=self.archive_tool,
            initial_history=profile_history,
            knowledge_base_root=self.knowledge_base_root,
        )
        self.interview_agent.guided_controller.ensure_state()
        
        self.phase = SessionPhase.INTERVIEW
        return await self.interview_agent.start()
    
    async def _handle_interview_input(
        self,
        user_input: str,
        candidate_questions: Optional[List[Dict[str, str]]] = None,
    ) -> QuestionResult:
        """处理采访阶段的用户输入"""
        # 首轮：如果有从上一次 session 归档加载的候选问题且当前未传入候选，则传入
        effective_candidates = candidate_questions
        if (
            not effective_candidates
            and self.initial_candidate_questions
            and not self._candidates_passed
        ):
            effective_candidates = self.initial_candidate_questions
            self._candidates_passed = True
            logger.info(
                f"Passing {len(effective_candidates)} previous-session candidate questions to InterviewAgent on first turn"
            )

        # 继续采访
        response = await self.interview_agent.handle_input(
            user_input,
            candidate_questions=effective_candidates,
        )
        self.conversation_history = list(self.interview_agent.conversation_history)

        # 检查InterviewAgent是否主动结束
        if self.interview_agent.is_completed:
            ending_msg = await self._start_ending()
            return QuestionResult(
                question=ending_msg,
                source="generated",
                candidate_question_id=None,
            )

        return response

    async def _handle_ending_input(self, user_input: str) -> QuestionResult:
        """处理结束阶段的用户输入"""
        return QuestionResult(
            question="今天的采访就到这里啦，非常感谢您的分享。期待下次再聊！",
            source="generated",
            candidate_question_id=None,
        )

    async def _start_ending(self) -> dict:
        """
        启动结束流程

        流程：
        1. 结束当前问题
        2. 生成总结和结束语（含下次采访建议问题及会话标题）
        3. 创建采访记录归档
        4. 归档对话记录

        Returns:
            dict with keys: message (str), title (str)
        """
        self.phase = SessionPhase.ENDING

        # 使用InterviewAgent的结束流程（现在返回 dict）
        ending_result = await self.interview_agent.generate_ending()
        self.conversation_history = list(self.interview_agent.conversation_history)

        # 兼容旧的字符串返回和新的dict返回
        if isinstance(ending_result, dict):
            ending_message = ending_result.get("message", "")
            title = ending_result.get("title", "")
            next_questions = ending_result.get("next_questions", [])
            summary = ending_result.get("summary", "")
        else:
            ending_message = ending_result
            title = ""
            next_questions = []
            summary = ending_result
        ending_message = self._sanitize_archive_text(ending_message)
        summary = self._sanitize_archive_text(summary)

        # 构建 session_data 用于采访记录归档
        # 把本轮对话原文也写入归档，避免重启后 agent 重复发问
        conversation_text = self._format_conversation_for_archive(
            self.interview_agent.conversation_history
        )
        session_data = {
            "summary": summary,
            "events": [],
            "people": [],
            "timepoints": [],
            "next_questions": next_questions,
            "unfinished_topics": self._stringify_topic(self.interview_agent.current_topic) or "",
            "current_topic": self._stringify_topic(self.interview_agent.current_topic) or "",
            "emotion_state": "",
            "topic_history": [
                self._stringify_topic(topic)
                for topic in self.interview_agent.topic_history
                if self._stringify_topic(topic)
            ],
            "structured_archive_status": "pending",
            "structured_archive_error": "",
            "structured_archive_failed_at": "",
            "conversation_text": conversation_text,
        }

        self.structured_archive_result = {"status": "pending", "error": None}

        # 先创建采访记录归档，确保结构化归档失败时原始 session 仍被留存。
        with observe_step("ending.create_session_archive", as_type="tool"):
            session_archive_path = await self.archive_tool.create_session_archive(self.user_id, session_data)

        try:
            with observe_step("ending.archive_conversation", as_type="tool"):
                organized_memory = await self.archive_tool.archive_conversation(
                    user_id=self.user_id,
                    conversation_history=self.conversation_history,
                    session_summary=self.interview_agent.session_summary,
                    raise_on_error=True,
                )

            events, people, timepoints = self._format_session_archive_items(organized_memory)
            session_data.update({
                "events": events,
                "people": people,
                "timepoints": timepoints,
                "structured_archive_status": "success",
                "structured_archive_error": "",
                "structured_archive_failed_at": "",
            })
            self.structured_archive_result = {"status": "success", "error": None}
        except Exception as e:
            error_message = self._sanitize_archive_text(str(e)) or e.__class__.__name__
            logger.error(f"Structured archive failed for user {self.user_id}: {error_message}")
            session_data.update({
                "structured_archive_status": "failed",
                "structured_archive_error": error_message,
                "structured_archive_failed_at": datetime.now().isoformat(),
            })
            self.structured_archive_result = {"status": "failed", "error": error_message}

        with observe_step("ending.update_session_archive", as_type="tool"):
            await self.archive_tool.update_session_archive(self.user_id, session_archive_path, session_data)
        
        self.phase = SessionPhase.CLOSED
        return {"message": ending_message, "title": title}

    def _format_session_archive_items(self, organized_memory) -> tuple[list[str], list[str], list[str]]:
        """把结构化归档结果转换成 session md 里的人类可读列表。"""
        if not organized_memory:
            return [], [], []

        events = []
        for event in getattr(organized_memory, "events", []) or []:
            title = getattr(event, "title", "") or ""
            time = getattr(event, "time", "") or ""
            description = self._sanitize_archive_text(getattr(event, "description", "") or "")
            label = " - ".join(part for part in [time, title] if part)
            if description:
                label = f"{label}: {description}" if label else description
            if label:
                events.append(label)

        people = []
        for person in getattr(organized_memory, "people", []) or []:
            name = getattr(person, "name", "") or ""
            relation = getattr(person, "relation", "") or ""
            description = self._sanitize_archive_text(getattr(person, "description", "") or "")
            label = "（".join([name, relation]) + "）" if name and relation else name or relation
            if description:
                label = f"{label}: {description}" if label else description
            if label:
                people.append(label)

        timepoints = []
        for update in getattr(organized_memory, "timeline_updates", []) or []:
            time_point = getattr(update, "time_point", "") or ""
            significance = getattr(update, "significance", "") or ""
            if "推断" in significance or "推算" in significance:
                continue
            label = f"{time_point}: {significance}" if significance else time_point
            if label:
                timepoints.append(label)

        return events, people, timepoints

    def _stringify_topic(self, topic) -> str:
        if not topic:
            return ""
        if isinstance(topic, str):
            return topic
        if isinstance(topic, dict):
            for key in ("event", "title", "name", "topic", "description"):
                value = topic.get(key)
                if value:
                    return str(value)
        return str(topic)

    def _sanitize_archive_text(self, text: str) -> str:
        if not text:
            return ""
        text = str(text)
        text = text.replace("具体职业不详，推测为钳工", "")
        text = text.replace("，推测为钳工", "")
        text = text.replace("推测为钳工", "")
        text = text.replace("推测为", "为")
        text = text.replace("技术骨干", "钳工")
        text = text.replace("资深钳工", "钳工")
        return text.strip().rstrip("，,")

    def _format_conversation_for_archive(self, conversation_history: list) -> str:
        """将本轮对话原文格式化为可写入归档的 Markdown。

        Returns:
            形如 "用户: …\n助手: …\n…" 的文本，每段截取不超过 200 字。
        """
        if not conversation_history:
            return ""
        lines = []
        for turn in conversation_history[-20:]:  # 最近 20 轮
            role = turn.get("role", "")
            content = str(turn.get("content", "")).strip()
            if not content:
                continue
            content = self._sanitize_archive_text(content)
            if len(content) > 200:
                content = content[:200].rstrip() + "..."
            if role == "user":
                lines.append(f"用户: {content}")
            elif role == "assistant":
                lines.append(f"助手: {content}")
        return "\n".join(lines)
    
    async def end_session(self) -> dict:
        """
        显式结束会话（由服务层在前端信号时调用）。

        确保前端手动结束时也会触发 Markdown 构建。

        Returns:
            dict with keys: message (str), title (str)
        """
        if self.phase == SessionPhase.CLOSED:
            return {"message": "会话已关闭", "title": ""}

        if self.interview_agent:
            self.conversation_history = list(self.interview_agent.conversation_history)
            return await self._start_ending()

        if self.profile_agent:
            profile_history = self.profile_agent.get_conversation_history()
            self.conversation_history = list(profile_history)
            with observe_step("profile.create_user_knowledge_base", as_type="tool"):
                await self.archive_tool.create_user_knowledge_base(
                    user_id=self.user_id,
                    conversation_history=profile_history,
                    profile_info=self.profile_agent.collected_info
                )
            with observe_step("profile.archive_conversation", as_type="tool"):
                await self.archive_tool.archive_conversation(
                    user_id=self.user_id,
                    conversation_history=profile_history,
                    session_summary="用户初始化对话结束归档"
                )
            self.phase = SessionPhase.CLOSED
            return {"message": "今天的采访就到这里啦，非常感谢您的分享。期待下次再聊！", "title": "基本信息收集"}

        if self.conversation_history:
            await self.archive_tool.archive_conversation(
                user_id=self.user_id,
                conversation_history=self.conversation_history,
                session_summary="采访结束归档"
            )

        self.phase = SessionPhase.CLOSED
        return {"message": "今天的采访就到这里啦，非常感谢您的分享。期待下次再聊！", "title": ""}
    
    def _parse_user_md(self, user_id: str) -> dict:
        """读取并解析 user.md。

        文件位于 knowledge_base/{user_id}/user.md，格式如：
            - 姓名: xxx
            - 年龄: 75
            - 职业: xxx
            ...
        """
        user_md_path = self.knowledge_base_root / user_id / "user.md"
        if not user_md_path.exists():
            return {}

        try:
            content = user_md_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read user.md at {user_md_path}: {e}")
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

        profile: dict = {}
        line_pattern = re.compile(r"^- (.+?):\s*(.+)$")
        for line in content.split("\n"):
            match = line_pattern.match(line.strip())
            if not match:
                continue
            cn_key = match.group(1).strip()
            value = match.group(2).strip()
            if cn_key in key_map:
                profile[key_map[cn_key]] = value
        return profile

    def _is_profile_complete(self, profile_info: dict) -> bool:
        """Return whether user.md has enough fields to skip profile collection."""
        if not isinstance(profile_info, dict):
            return False
        return all(
            profile_info.get(field)
            for field in ProfileCollectionAgent.REQUIRED_FIELDS
        )

    def _compute_address_style(self, profile_info: dict) -> str:
        """根据被采访者的年龄、姓名、性别提示计算称呼方式。

        规则：
        - 年龄 > 70，有姓名：{姓}爷爷 / {姓}奶奶
        - 年龄 50-70，有姓名：{姓}叔叔 / {姓}阿姨
        - 年龄 < 50，有姓名：{姓}先生 / {姓}女士
        - 年龄、姓名或性别未知：“您”

        性别推断仅依赖 family_status中的提示。
        """
        if not isinstance(profile_info, dict) or not profile_info:
            return "您"

        name = profile_info.get("name")
        age_value = profile_info.get("age")
        family_status = profile_info.get("family_status") or ""
        gender_value = str(profile_info.get("gender") or "").strip().lower()

        # 解析年龄
        if age_value is None or age_value == "":
            return "您"
        age_match = re.search(r"\d+", str(age_value))
        if not age_match:
            return "您"
        try:
            age_int = int(age_match.group())
        except (TypeError, ValueError):
            return "您"

        # 姓氏（中文姓名取首字）
        if not name:
            return "您"
        surname = str(name).strip()
        if not surname:
            return "您"
        surname = surname[0]

        # 优先使用外部画像提供的性别；缺失时再从 family_status 保守推断。
        gender: Optional[str] = None
        if gender_value in {"女", "女性", "female", "f", "woman"}:
            gender = "female"
        elif gender_value in {"男", "男性", "male", "m", "man"}:
            gender = "male"
        elif any(token in family_status for token in ["丈夫", "老公"]):
            gender = "female"
        elif any(token in family_status for token in ["妻子", "老婆", "夫人"]):
            gender = "male"

        if gender is None:
            return "您"

        if age_int > 70:
            return f"{surname}奶奶" if gender == "female" else f"{surname}爷爷"
        elif age_int >= 50:
            return f"{surname}阿姨" if gender == "female" else f"{surname}叔叔"
        else:
            return f"{surname}女士" if gender == "female" else f"{surname}先生"
