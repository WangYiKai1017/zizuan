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
            
            # 检查是否包含除index.md之外的其他Markdown文件
            has_other_md_files = False
            for md_file in self.knowledge_base_path.rglob("*.md"):
                if md_file.name != "index.md":
                    has_other_md_files = True
                    break
            
            if not has_other_md_files:
                logger.info(f"No other Markdown files found except index.md in: {self.knowledge_base_path}")
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
        1. 加载历史对话记录
        2. 加载最近一次的 session 归档作为上下文
        3. 分析需要的知识库信息
        4. 执行知识库查询
        5. 生成继续对话的Prompt（携带上次 session 上下文）
        6. 进入采访流程，并把上次准备好的问题作为候选注入首轮
        """
        self.has_profile = True

        # 0. 读取user.md计算称呼方式（user.md 不存在时使用默认 "您"）
        profile_info = self._parse_user_md(self.user_id)
        self.address_style = self._compute_address_style(profile_info)
        logger.info(f"Computed address_style for resumed session: {self.address_style}")

        # 0.1 查找并解析最新的 session 归档
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

        # 0.2 上次准备好的问题 → 转为候选问题格式，注入首轮 handle_input
        next_questions = prev_context.get("next_questions", []) or []
        if next_questions:
            self.initial_candidate_questions = [
                {"id": f"prev_q_{i}", "question": q}
                for i, q in enumerate(next_questions, 1)
            ]
            self._candidates_passed = False
            logger.info(f"Loaded {len(self.initial_candidate_questions)} candidate questions from previous session")

        # 1. 从知识库中读取最新的对话记录
        history = await self.memory_manager.repository.get_latest_conversation_records(self.user_id, 5)
        self.conversation_history = history
        
        # 2. 分析需要的知识库信息
        query_prompt = self._build_resume_analysis_prompt(history)
        analysis_result = await self.llm_service.invoke(
            prompt=query_prompt,
            temperature=0.3
        )
        analysis_result = analysis_result.content
        
        # 3. 执行知识库查询（避免重复查询）
        query_hash = hash(analysis_result)
        if query_hash in self.current_round_queries:
            logger.info(f"重复查询请求，已跳过：{analysis_result[:50]}...")
            knowledge_context = ""
        else:
            knowledge_context = await self.query_tool.query(
                user_id=self.user_id,
                query=analysis_result,
                max_iterations=5
            )
            self.current_round_queries.add(query_hash)  # 记录已查询的请求
        
        # 4. 缓存知识库查询结果
        self.cache_tool.append_cache(
            session_id=self.user_id,
            content=knowledge_context
        )
        
        # 5. 生成继续对话的Prompt（包含上次 session 上下文）
        resume_prompt = self._build_resume_dialogue_prompt(
            history=history,
            knowledge_context=knowledge_context,
            prev_context=prev_context,
        )
        
        # 6. 初始化InterviewAgent并启动
        self.interview_agent = InterviewAgent(
            user_id=self.user_id,
            llm_service=self.llm_service,
            memory_manager=self.memory_manager,
            cache_tool=self.cache_tool,
            query_tool=self.query_tool,
            archive_tool=self.archive_tool,
            resume_prompt=resume_prompt,
            initial_history=history,
            address_style=self.address_style,
        )

        # 6.1 将上次的话题历史与当前话题方向注入 InterviewAgent
        prev_topic_history = prev_context.get("topic_history", []) or []
        if prev_topic_history:
            self.interview_agent.topic_history = list(prev_topic_history)
        prev_current_topic = prev_context.get("current_topic")
        if prev_current_topic:
            self.interview_agent.current_topic = prev_current_topic

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
        
        # 创建初始化Agent（不使用时间限制，仅依赖必填字段检查）
        self.profile_agent = ProfileCollectionAgent(
            user_id=self.user_id,
            llm_service=self.llm_service,
            memory_manager=self.memory_manager,
            max_duration_minutes=10**9
        )
        
        # 执行初始化流程
        welcome_message = await self.profile_agent.start()
        
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
            await self._on_profile_complete()

        return QuestionResult(
            question=response,
            source="generated",
            candidate_question_id=None,
        )
    
    async def _on_profile_complete(self):
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
        await self.archive_tool.create_user_knowledge_base(
            user_id=self.user_id,
            conversation_history=profile_history,
            profile_info=self.profile_agent.collected_info
        )

        # 2.1 将当前内容归档
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
            address_style=self.address_style,
        )
        
        self.phase = SessionPhase.INTERVIEW
    
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

    async def _start_ending(self) -> str:
        """
        启动结束流程
        
        流程：
        1. 结束当前问题
        2. 生成总结和结束语（含下次采访建议问题）
        3. 创建采访记录归档
        4. 归档对话记录
        """
        self.phase = SessionPhase.ENDING
        
        # 使用InterviewAgent的结束流程（现在返回 dict）
        ending_result = await self.interview_agent.generate_ending()
        self.conversation_history = list(self.interview_agent.conversation_history)

        # 兼容旧的字符串返回和新的dict返回
        if isinstance(ending_result, dict):
            ending_message = ending_result.get("message", "")
            next_questions = ending_result.get("next_questions", [])
            summary = ending_result.get("summary", "")
        else:
            ending_message = ending_result
            next_questions = []
            summary = ending_result
        ending_message = self._sanitize_archive_text(ending_message)
        summary = self._sanitize_archive_text(summary)

        # 先归档对话记录，让 session 归档可以引用本次结构化提取结果。
        organized_memory = await self.archive_tool.archive_conversation(
            user_id=self.user_id,
            conversation_history=self.conversation_history,
            session_summary=self.interview_agent.session_summary
        )

        events, people, timepoints = self._format_session_archive_items(organized_memory)

        # 构建 session_data 用于采访记录归档
        session_data = {
            "summary": summary,
            "events": events,
            "people": people,
            "timepoints": timepoints,
            "next_questions": next_questions,
            "unfinished_topics": self._stringify_topic(self.interview_agent.current_topic) or "",
            "current_topic": self._stringify_topic(self.interview_agent.current_topic) or "",
            "emotion_state": "",
            "topic_history": [
                self._stringify_topic(topic)
                for topic in self.interview_agent.topic_history
                if self._stringify_topic(topic)
            ],
        }

        # 创建采访记录归档
        await self.archive_tool.create_session_archive(self.user_id, session_data)
        
        self.phase = SessionPhase.CLOSED
        return ending_message

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
    
    async def end_session(self) -> str:
        """
        显式结束会话（由服务层在前端信号时调用）。

        确保前端手动结束时也会触发 Markdown 构建。
        """
        if self.phase == SessionPhase.CLOSED:
            return "会话已关闭"

        if self.interview_agent:
            self.conversation_history = list(self.interview_agent.conversation_history)
            return await self._start_ending()

        if self.profile_agent:
            profile_history = self.profile_agent.get_conversation_history()
            self.conversation_history = list(profile_history)
            await self.archive_tool.create_user_knowledge_base(
                user_id=self.user_id,
                conversation_history=profile_history,
                profile_info=self.profile_agent.collected_info
            )
            await self.archive_tool.archive_conversation(
                user_id=self.user_id,
                conversation_history=profile_history,
                session_summary="用户初始化对话结束归档"
            )
            self.phase = SessionPhase.CLOSED
            return "今天的采访就到这里啦，非常感谢您的分享。期待下次再聊！"

        if self.conversation_history:
            await self.archive_tool.archive_conversation(
                user_id=self.user_id,
                conversation_history=self.conversation_history,
                session_summary="采访结束归档"
            )

        self.phase = SessionPhase.CLOSED
        return "今天的采访就到这里啦，非常感谢您的分享。期待下次再聊！"
    
    def _build_resume_analysis_prompt(self, history: list) -> str:
        """
        构建历史对话分析Prompt
        
        目标：让大模型分析之前的对话记录，判断需要获取哪些知识库信息
        """
        history_text = self._format_history(history)
        
        prompt = f"""## 任务说明

你是一位采访助手，正在分析老人的历史对话记录。
你的任务是根据之前的对话内容，判断需要从知识库中查询哪些信息来继续本次对话。

## 历史对话记录

{history_text}

## 分析要求

请分析以下内容：
1. 上次对话停在了什么话题？
2. 有哪些未展开的重要事件或人物？
3. 用户提到过但未详细讨论的内容？
4. 需要补充哪些背景信息？

## 输出格式

请直接输出一个知识库查询语句，用于检索相关信息。例如：
- "童年时期的家庭生活和学校经历"
- "在工厂工作期间的重要事件和同事关系"
- "子女成长过程中的重要时刻"

注意：只输出一个查询语句，不要其他解释。"""
        return prompt
    
    def _build_resume_dialogue_prompt(
        self,
        history: list,
        knowledge_context: str,
        prev_context: Optional[dict] = None,
    ) -> str:
        """
        构建继续对话的Prompt
        
        目标：总结上次对话，结合知识库内容与上次 session 归档，生成开场白
        """
        history_text = self._format_history(history)
        prev_context = prev_context or {}

        prev_summary = (prev_context.get("summary") or "").strip()
        unfinished_topics = prev_context.get("unfinished_topics") or []
        prev_current_topic = prev_context.get("current_topic") or ""
        topic_history = prev_context.get("topic_history") or []

        # 裁剪过长的摘要
        summary_snippet = prev_summary[:200] if prev_summary else ""
        unfinished_str = "、".join(unfinished_topics[:5]) if unfinished_topics else ""
        topic_history_str = "、".join(topic_history[:8]) if topic_history else ""

        prev_section = ""
        if prev_summary or unfinished_topics or prev_current_topic or topic_history:
            prev_section = f"""## 上次采访上下文

- 上次采访摘要：{summary_snippet or '（无）'}
- 上次未聊完的话题：{unfinished_str or '（无）'}
- 上次话题方向：{prev_current_topic or '（无）'}
- 已探索的话题：{topic_history_str or '（无）'}

"""

        address = self.address_style or "您"

        prompt = f"""## 任务说明

你是一位温暖、专业的采访记者，正在采访一位老人撰写自传。
用户之前已经有过对话，现在需要你根据历史记录、知识库内容及上次 session 上下文，生成一段欢迎回来的开场白。

## 被采访者称呼

{address}

## 上次对话记录

{history_text}

{prev_section}## 知识库查询结果

{knowledge_context}

## 输出要求

请生成一段开场白，要求：
1. 以“{address}，欢迎回来”之类的问候开始，体现上次交谈后的延续
2. 简要回顾上次聊到的主要内容或摘要（1-2句话）
3. 如果有未聊完的话题，可以提及并试探是否愿意继续
4. 最后提出一个轻柔、开放的问题让老人选择今天从哪里开始
5. 语气温暖、亲切，像老朋友聊天一样，字数控制在 80字左右

## 示例

"张爷爷，欢迎回来！上回咱们聊到您在部队服役的那段日子，听得我都入迷了。上次还有些话题没聊完，今天您想从哪里接着讲呢？"

请生成开场白：
"""
        return prompt
    
    def _format_history(self, history: list) -> str:
        """格式化历史对话记录"""
        lines = []
        for turn in history[-10:]:  # 只取最近10轮
            lines.append(f"用户: {turn.get('content', '')}")
        return "\n".join(lines)

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
            "姓名": "name",
            "年龄": "age",
            "职业": "occupation",
            "家庭状况": "family_status",
            "居住情况": "living_arrangement",
            "故事期望": "story_expectation",
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

    def _compute_address_style(self, profile_info: dict) -> str:
        """根据被采访者的年龄、姓名、性别提示计算称呼方式。

        规则：
        - 年龄 > 70，有姓名：{姓}爷爷 / {姓}奶奶
        - 年龄 50-70，有姓名：{姓}叔叔 / {姓}阿姨
        - 年龄 < 50，有姓名：{姓}先生 / {姓}女士
        - 年龄未知或姓名未知：“您”

        性别推断仅依赖 family_status中的提示。
        """
        if not isinstance(profile_info, dict) or not profile_info:
            return "您"

        name = profile_info.get("name")
        age_value = profile_info.get("age")
        family_status = profile_info.get("family_status") or ""

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

        # 性别推断：family_status 中出现“丈夫/老公”默认为女性；
        # 出现“妻子/老婆/夫人”默认为男性。
        gender: Optional[str] = None
        if any(token in family_status for token in ["丈夫", "老公"]):
            gender = "female"
        elif any(token in family_status for token in ["妻子", "老婆", "夫人"]):
            gender = "male"

        if age_int > 70:
            return f"{surname}奶奶" if gender == "female" else f"{surname}爷爷"
        elif age_int >= 50:
            return f"{surname}阿姨" if gender == "female" else f"{surname}叔叔"
        else:
            return f"{surname}女士" if gender == "female" else f"{surname}先生"
