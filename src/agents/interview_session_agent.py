from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import logging

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
    - 时间控制（15分钟总时长，初始化5分钟）
    - 知识库协调
    
    启动逻辑：
    1. 根据user_id检查知识库是否存在
    2. 存在 → 加载历史对话，进入采访流程
    3. 不存在 → 启动用户初始化流程
    
    时间规则：
    - 总时长：15分钟
    - 含初始化：采访流程缩减至10分钟
    - 初始化独立限制：5分钟
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
        self.session_start_time: Optional[datetime] = None
        self.total_duration_minutes = 15
        self.profile_duration_minutes = 5
        # self.profile_duration_minutes = 1
        self.has_profile = False  # 是否完成了初始化
        self.five_minute_archived = False  # 是否已完成前五分钟归档
        
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
        
    async def start(self) -> str:
        """
        启动会话
        
        Returns:
            开场白或欢迎语
        """
        self.session_start_time = datetime.now()
        
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
        2. 分析需要的知识库信息
        3. 执行知识库查询
        4. 生成继续对话的Prompt
        5. 进入采访流程
        """
        self.has_profile = True
        
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
        await self.cache_tool.append_cache(
            session_id=self.user_id,
            content=knowledge_context
        )
        
        # 5. 生成继续对话的Prompt
        resume_prompt = self._build_resume_dialogue_prompt(
            history=history,
            knowledge_context=knowledge_context
        )
        
        # 6. 初始化InterviewAgent并启动
        self.interview_agent = InterviewAgent(
            user_id=self.user_id,
            llm_service=self.llm_service,
            memory_manager=self.memory_manager,
            cache_tool=self.cache_tool,
            query_tool=self.query_tool,
            archive_tool=self.archive_tool,
            duration_minutes=15,  # 老用户完整15分钟
            resume_prompt=resume_prompt,
            initial_history=history,
        )
        
        self.phase = SessionPhase.INTERVIEW
        return await self.interview_agent.start()
    
    async def _start_profile_collection(self) -> str:
        """
        启动用户初始化流程
        
        流程：
        1. 创建ProfileCollectionAgent
        2. 执行信息收集（最长5分钟）
        3. 收集完成或超时后，生成基础知识库
        4. 将对话记录传递给采访流程
        """
        self.phase = SessionPhase.PROFILE_COLLECTION
        
        # 创建初始化Agent
        self.profile_agent = ProfileCollectionAgent(
            user_id=self.user_id,
            llm_service=self.llm_service,
            memory_manager=self.memory_manager,
            max_duration_minutes=self.profile_duration_minutes
        )
        
        # 执行初始化流程
        welcome_message = await self.profile_agent.start()
        
        # 注意：初始化Agent会持续运行，直到收集完成或超时
        # 超时后会触发 _on_profile_complete
        
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
        
        # 4. 启动采访流程（缩减至10分钟）
        self.interview_agent = InterviewAgent(
            user_id=self.user_id,
            llm_service=self.llm_service,
            memory_manager=self.memory_manager,
            cache_tool=self.cache_tool,
            query_tool=self.query_tool,
            archive_tool=self.archive_tool,
            duration_minutes=10,  # 新用户只有10分钟采访时间
            initial_history=profile_history
        )
        
        self.phase = SessionPhase.INTERVIEW
    
    async def _handle_interview_input(
        self,
        user_input: str,
        candidate_questions: Optional[List[Dict[str, str]]] = None,
    ) -> QuestionResult:
        """处理采访阶段的用户输入"""
        # 检查时间限制
        elapsed = self._get_elapsed_minutes()

        if elapsed >= self.total_duration_minutes:
            # 超时，进入结束流程
            ending_msg = await self._start_ending()
            return QuestionResult(
                question=ending_msg,
                source="generated",
                candidate_question_id=None,
            )

        # 未超时，继续采访
        response = await self.interview_agent.handle_input(
            user_input,
            candidate_questions=candidate_questions,
        )
        self.conversation_history = list(self.interview_agent.conversation_history)

        # 检查是否达到前五分钟，触发归档。放在本轮处理之后，确保归档包含触发 checkpoint 的采访内容。
        if not self.five_minute_archived and elapsed >= 5:
            logger.info(f"达到前五分钟，触发归档，已用时间：{elapsed:.1f}分钟")
            await self.archive_tool.archive_conversation(
                user_id=self.user_id,
                conversation_history=self.conversation_history,
                session_summary="前五分钟对话存档"
            )
            self.five_minute_archived = True

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

    async def end_session(self) -> str:
        """
        主动结束会话并归档当前已收集的内容。

        用于 /api/interview/end，确保前端手动结束时也会触发 Markdown 构建。
        """
        if self.phase == SessionPhase.CLOSED:
            return "今天的采访已经结束，期待下次再聊。"

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
    
    async def _start_ending(self) -> str:
        """
        启动结束流程
        
        流程：
        1. 结束当前问题
        2. 生成总结和结束语
        3. 明确下次话题
        4. 归档对话记录
        """
        self.phase = SessionPhase.ENDING
        
        # 使用InterviewAgent的结束流程
        ending_message = await self.interview_agent.generate_ending()
        self.conversation_history = list(self.interview_agent.conversation_history)
        
        # 归档对话记录
        await self.archive_tool.archive_conversation(
            user_id=self.user_id,
            conversation_history=self.conversation_history,
            session_summary=self.interview_agent.session_summary
        )
        
        self.phase = SessionPhase.CLOSED
        return ending_message
    
    def _get_elapsed_minutes(self) -> float:
        """获取已用时长（分钟）"""
        if not self.session_start_time:
            return 0
        elapsed = datetime.now() - self.session_start_time
        return elapsed.total_seconds() / 60
    
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
        knowledge_context: str
    ) -> str:
        """
        构建继续对话的Prompt
        
        目标：总结上次对话，结合知识库内容，生成开场白
        """
        history_text = self._format_history(history)
        
        prompt = f"""## 任务说明

你是一位温暖、专业的采访记者，正在采访一位老人撰写自传。
用户之前已经有过对话，现在需要你根据历史记录和知识库内容，继续上次的对话。

## 上次对话记录

{history_text}

## 知识库查询结果

{knowledge_context}

## 输出要求

请生成一段开场白，要求：
1. 简要回顾上次对话的亮点（1-2句话）
2. 根据知识库内容，提出一个自然延续的问题
3. 语气温暖、亲切，像老朋友聊天一样
4. 不要让用户感到压力，引导他继续分享

## 示例

"上次我们聊到您在工厂工作的那段经历，听起来特别有意思。我记得您提到过张师傅对您帮助很大，能再跟我多说说当时的情况吗？"

请生成开场白：
"""
        return prompt
    
    def _format_history(self, history: list) -> str:
        """格式化历史对话记录"""
        lines = []
        for turn in history[-10:]:  # 只取最近10轮
            lines.append(f"用户: {turn.get('content', '')}")
        return "\n".join(lines)
