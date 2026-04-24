# src/core/conversation_orchestrator.py
from typing import Optional, List, Dict, Any
import asyncio
from datetime import datetime, timedelta
import logging
from enum import Enum
from dataclasses import dataclass, field

from src.services.llm_service import LLMService
from src.services.emotion_detector import EmotionDetector
from src.services.knowledge_base_querier import KnowledgeBaseQuerier
from src.services.question_generator import QuestionGenerator
from src.services.content_summarizer import ContentSummarizer
from src.services.memory_manager import MemoryManager
from src.storage.memory_repository import MemoryRepository
from src.storage.markdown_file_manager import MarkdownFileManager
from src.core.event_bus import EventBus, EventType, get_event_bus
from src.models import (
    SessionState, ConversationTurn, EmotionResult, MemoryQueryResult,
    AgentResponse, HandoffPackage, SessionSummary, ProgressInfo, CollectedData,
)
from src.enums import StateType, PhaseType, StrategyType
from src.config.llm_config import LLMConfig
from src.config.profile_questions import ProfileQuestionBank

logger = logging.getLogger(__name__)


class OrchestratorConfig:
    """主控器配置"""
    # 原有配置
    emotion_timeout: float = 3.0
    query_timeout: float = 5.0
    summary_timeout: float = 10.0
    handoff_turn_threshold: int = 10
    pause_inactivity_minutes: int = 5
    
    # 新增：时长控制配置
    session_duration_minutes: int = 15          # 会话时长限制（分钟）
    time_warning_threshold: float = 0.8         # 时间警告阈值（提前20%提示）
    time_warning_enabled: bool = True           # 是否启用时间警告
    profile_collection_enabled: bool = True     # 是否启用首次信息收集


class ProfileCollectionState(str, Enum):
    """首次信息收集状态"""
    INIT_PROFILE = "init_profile"               # 初始化状态
    COLLECT_BASIC = "collect_basic"             # 收集基础信息
    COLLECT_DETAIL = "collect_detail"           # 收集详细信息
    READY = "ready"                             # 收集完成，准备进入主对话


@dataclass
class SessionTiming:
    """会话计时信息"""
    start_time: datetime
    duration_minutes: int
    warning_threshold: float = 0.8
    warning_issued: bool = False
    time_up_issued: bool = False
    
    def get_elapsed_seconds(self) -> float:
        """获取已流逝的秒数"""
        return (datetime.now() - self.start_time).total_seconds()
    
    def get_elapsed_minutes(self) -> float:
        """获取已流逝的分钟数"""
        return self.get_elapsed_seconds() / 60
    
    def get_remaining_minutes(self) -> float:
        """获取剩余分钟数"""
        return max(0, self.duration_minutes - self.get_elapsed_minutes())
    
    def should_warn(self) -> bool:
        """是否应该发出时间警告"""
        if self.warning_issued or self.time_up_issued:
            return False
        elapsed_ratio = self.get_elapsed_minutes() / self.duration_minutes
        return elapsed_ratio >= self.warning_threshold
    
    def is_time_up(self) -> bool:
        """是否时间到了"""
        if self.time_up_issued:
            return False
        return self.get_elapsed_minutes() >= self.duration_minutes
    
    def mark_warning_issued(self):
        """标记警告已发出"""
        self.warning_issued = True
    
    def mark_time_up_issued(self):
        """标记时间到已处理"""
        self.time_up_issued = True


@dataclass
class ProfileData:
    """收集的用户画像数据"""
    # 基础信息
    name: Optional[str] = None                  # 姓名
    age: Optional[int] = None                   # 年龄
    gender: Optional[str] = None                # 性别
    birth_year: Optional[int] = None             # 出生年份
    birth_place: Optional[str] = None            # 出生地
    
    # 职业信息
    occupation: Optional[str] = None             # 职业
    occupation_history: List[str] = field(default_factory=list)  # 职业经历
    
    # 家庭信息
    family_status: Optional[str] = None          # 家庭状况（已婚/丧偶等）
    children_count: Optional[int] = None         # 子女数量
    living_arrangement: Optional[str] = None     # 居住安排
    
    # 健康状况
    health_status: Optional[str] = None          # 健康状况
    
    # 采集状态
    collection_state: ProfileCollectionState = ProfileCollectionState.INIT_PROFILE
    collected_fields: List[str] = field(default_factory=list)    # 已收集的字段
    missing_fields: List[str] = field(default_factory=list)     # 缺失的字段
    
    def is_complete(self) -> bool:
        """检查基本信息是否完整"""
        required_fields = ["name", "age", "occupation"]
        return all(getattr(self, f) is not None for f in required_fields)


@dataclass
class SessionEndGuideContent:
    """会话结束引导内容"""
    message: str                                # 结束消息
    summary: str                                # 本次会话总结
    next_topic: str                             # 下次主题提示
    collected_highlights: List[str] = field(default_factory=list)  # 收集的亮点


class ConversationOrchestrator:
    """
    对话主控器 - 整个问答引导层的核心控制器
    
    职责：
    - 协调所有子Agent异步工作
    - 管理对话状态流转
    - 处理用户输入并生成回复
    - 触发内容归纳和交接
    
    使用场景：
    - 外部系统通过此类与问答引导层交互
    
    示例：
    ```python
    orchestrator = ConversationOrchestrator(config)
    await orchestrator.initialize_session(user_profile)
    
    response = await orchestrator.process_turn("用户输入")
    print(response.message)
    
    handoff = await orchestrator.terminate_session()
    ```
    """
    
    def __init__(
        self,
        llm_config: LLMConfig,
        memory_base_path: str = "memory",
        config: OrchestratorConfig = None,
    ):
        """初始化"""
        self.config = config or OrchestratorConfig()
        
        # 初始化所有组件
        self.llm_service = LLMService(llm_config)
        self.file_manager = MarkdownFileManager(memory_base_path)
        self.repository = MemoryRepository(self.file_manager)
        self.memory_manager = MemoryManager(self.repository)
        
        self.emotion_detector = EmotionDetector(self.llm_service)
        self.knowledge_querier = KnowledgeBaseQuerier(
            self.file_manager, self.llm_service
        )
        self.question_generator = QuestionGenerator(self.llm_service)
        self.content_summarizer = ContentSummarizer(
            self.llm_service, self.memory_manager
        )
        
        self.event_bus = get_event_bus()
        
        # 当前会话
        self.current_session: Optional[SessionState] = None
        
        # 会话计时
        self.session_timing: Optional[SessionTiming] = None
        
        # 用户画像数据
        self.profile_data: Optional[ProfileData] = None
    
    async def initialize_session(
        self,
        user_profile: dict,
        strategy: StrategyType = StrategyType.SPARKLE_FIRST,
    ) -> SessionState:
        """初始化会话"""
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 初始化会话计时器
        self.session_timing = SessionTiming(
            start_time=datetime.now(),
            duration_minutes=self.config.session_duration_minutes,
            warning_threshold=self.config.time_warning_threshold,
        )
        
        # 检查是否首次会话，启用画像收集
        if self.config.profile_collection_enabled:
            existing_profile = await self._load_existing_profile()
            if not existing_profile:
                # 首次会话，进入画像收集流程
                self.profile_data = ProfileData()
                self.profile_data.collection_state = ProfileCollectionState.INIT_PROFILE
        
        self.current_session = SessionState(
            session_id=session_id,
            strategy=strategy,
            user_preferences=user_profile,
        )
        
        self.event_bus.emit(EventType.SESSION_STARTED, {
            "session_id": session_id,
            "user_profile": user_profile,
            "is_first_session": existing_profile is None,
        })
        
        logger.info(f"Session initialized: {session_id}")
        return self.current_session
    
    async def process_turn(self, user_input: str) -> AgentResponse:
        """处理一轮对话"""
        if not self.current_session:
            raise RuntimeError("Session not initialized")
        
        # 检查是否在画像收集流程中
        if self.profile_data and self.profile_data.collection_state != ProfileCollectionState.READY:
            return await self._process_profile_collection_turn(user_input)
        
        # 检查会话时长
        if self.session_timing:
            # 检查时间警告
            if self.session_timing.should_warn():
                self.session_timing.mark_warning_issued()
                self.event_bus.emit(EventType.SESSION_TIME_WARNING, {
                    "remaining_minutes": self.session_timing.get_remaining_minutes(),
                    "session_id": self.current_session.session_id,
                })
            
            # 检查时间是否到
            if self.session_timing.is_time_up():
                self.session_timing.mark_time_up_issued()
                return await self._handle_session_time_up()
        
        state = self.current_session
        state.current_state = StateType.COLLECT
        
        # 创建对话轮次
        turn = ConversationTurn(
            turn_id=state.turn_count + 1,
            user_input=user_input,
        )
        
        # 并行启动异步任务
        emotion_task = asyncio.create_task(
            self.emotion_detector.detect(user_input, state.conversation_history)
        )
        # 使用file_manager的base_path作为查询的target_path
        target_path = str(self.file_manager.base_path)
        knowledge_task = asyncio.create_task(
            self.knowledge_querier.query(user_input, target_path, state)
        )
        
        # 内容归纳延迟执行（不等待）
        summary_task = asyncio.create_task(
            self.content_summarizer.summarize_async(
                user_input, turn.turn_id, state.session_id
            )
        )
        
        # 等待关键任务（带超时保护）
        try:
            emotion_result = await asyncio.wait_for(
                emotion_task, timeout=self.config.emotion_timeout
            )
        except asyncio.TimeoutError:
            emotion_result = EmotionResult.default_neutral()
            logger.warning("Emotion detection timeout")
        
        try:
            knowledge_result = await asyncio.wait_for(
                knowledge_task, timeout=self.config.query_timeout
            )
        except asyncio.TimeoutError:
            knowledge_result = MemoryQueryResult.empty()
            logger.warning("Knowledge query timeout")
        
        # 处理情绪
        if emotion_result.needs_special_handling:
            state.current_state = StateType.PAUSE
        
        # 生成问题
        question = await self.question_generator.generate(
            user_input, emotion_result, knowledge_result, state
        )
        
        # 更新状态
        turn.agent_response = question
        turn.emotion = emotion_result.emotion_type
        state.add_turn(turn)
        state.update_from_emotion(emotion_result)
        
        # 更新短期记忆
        self.memory_manager.add_conversation_turn({
            "turn_id": turn.turn_id,
            "user_input": user_input,
            "agent_response": question,
        })
        
        # 检查是否需要交接
        handoff_triggered = self._check_handoff_condition(state)
        
        if handoff_triggered:
            state.current_state = StateType.HANDOFF
        
        # 发布事件
        self.event_bus.emit(EventType.TURN_COMPLETED, {
            "turn_id": turn.turn_id,
            "emotion": emotion_result.emotion_type,
        })
        
        return AgentResponse(
            message=question,
            state_update=state.to_summary(),
            should_pause=emotion_result.should_pause(),
            pause_reason=emotion_result.emotion_type if emotion_result.should_pause() else None,
            handoff_triggered=handoff_triggered,
        )
    
    def _check_handoff_condition(self, state: SessionState) -> bool:
        """检查交接条件"""
        conditions = [
            state.turn_count >= self.config.handoff_turn_threshold,
            all(c >= 0.8 for c in state.coverage.values()),
        ]
        return any(conditions)
    
    async def prepare_handoff(self) -> HandoffPackage:
        """准备交接包"""
        state = self.current_session
        
        # 最终归纳
        summary = await self.content_summarizer.prepare_handoff(state)
        
        # 构建交接包
        handoff = HandoffPackage(
            handoff_id=f"handoff_{state.session_id}",
            session_info=SessionSummary(
                session_id=state.session_id,
                total_turns=state.turn_count,
                duration_minutes=0,  # TODO: 计算
                strategy_used=state.strategy,
            ),
            collection_progress={
                phase: ProgressInfo(
                    coverage=cov,
                    events=len([e for e in state.collected_events]),
                    people=len([p for p in state.collected_people]),
                )
                for phase, cov in state.coverage.items()
            },
            collected_data=CollectedData(
                events=summary.extracted_info.events,
                people=summary.extracted_info.people,
                timeline=summary.extracted_info.time_markers,
                themes=summary.extracted_info.themes,
            ),
            raw_conversations_path=f"conversations/{state.session_id}.md",
            pending_questions=state.pending_questions,
        )
        
        self.event_bus.emit(EventType.HANDOFF_READY, handoff)
        
        return handoff
    
    async def terminate_session(self) -> HandoffPackage:
        """终止会话"""
        handoff = await self.prepare_handoff()
        
        self.event_bus.emit(EventType.SESSION_TERMINATED, {
            "session_id": self.current_session.session_id,
        })
        
        logger.info(f"Session terminated: {self.current_session.session_id}")
        
        return handoff
    
    async def pause_session(self) -> None:
        """暂停会话"""
        if self.current_session:
            self.current_session.current_state = StateType.PAUSE
            self.event_bus.emit(EventType.SESSION_PAUSED, {
                "session_id": self.current_session.session_id,
            })
    
    async def resume_session(self, session_id: str) -> SessionState:
        """恢复会话"""
        # TODO: 从持久化存储加载
        pass
    
    async def _load_existing_profile(self) -> Optional[dict]:
        """加载现有用户画像"""
        # 简化实现，实际应该从持久化存储加载
        return None
    
    async def _process_profile_collection_turn(self, user_input: str) -> AgentResponse:
        """
        处理画像收集流程的一轮对话
        """
        state = self.profile_data.collection_state
        
        # 根据当前状态处理输入
        if state == ProfileCollectionState.INIT_PROFILE:
            return await self._handle_init_profile(user_input)
        elif state == ProfileCollectionState.COLLECT_BASIC:
            return await self._handle_collect_basic(user_input)
        elif state == ProfileCollectionState.COLLECT_DETAIL:
            return await self._handle_collect_detail(user_input)
        
        # 默认返回
        return AgentResponse(
            message="",
            state_update={},
            is_profile_collection=True,
        )
    
    async def _handle_init_profile(self, user_input: str) -> AgentResponse:
        """处理初始化状态"""
        # 发送欢迎语和过渡话术
        welcome_message = (
            f"您好！欢迎使用老人自传服务。\n\n"
            f"我是您的故事记录助手，很高兴能够帮您记录和整理人生的美好回忆。\n\n"
            f"{ProfileQuestionBank.TRANSITION_PHRASES['to_basic']}"
        )
        
        # 更新状态
        self.profile_data.collection_state = ProfileCollectionState.COLLECT_BASIC
        self.profile_data.collected_fields.append("init")
        
        # 记录欢迎语
        self.event_bus.emit(EventType.SESSION_STARTED, {
            "session_id": self.current_session.session_id,
        })
        
        return AgentResponse(
            message=welcome_message,
            state_update={"collection_state": self.profile_data.collection_state.value},
            is_profile_collection=True,
            next_question=ProfileQuestionBank.BASIC_QUESTIONS["name"]["question"],
        )
    
    async def _handle_collect_basic(self, user_input: str) -> AgentResponse:
        """处理基础信息收集"""
        # 解析用户输入，更新画像数据
        extracted_info = await self._extract_profile_field(user_input)
        
        # 更新画像数据
        if extracted_info:
            for field, value in extracted_info.items():
                setattr(self.profile_data, field, value)
                self.profile_data.collected_fields.append(field)
        
        # 确定下一个需要收集的字段
        next_field = self._get_next_required_field(
            ProfileQuestionBank.BASIC_QUESTIONS,
            self.profile_data.collected_fields
        )
        
        if next_field:
            # 继续收集基础信息
            return AgentResponse(
                message="",
                state_update={
                    "collection_state": self.profile_data.collection_state.value,
                    "collected_fields": self.profile_data.collected_fields,
                },
                is_profile_collection=True,
                next_question=ProfileQuestionBank.BASIC_QUESTIONS[next_field]["question"],
            )
        else:
            # 基础信息收集完成，进入详细信息收集
            self.profile_data.collection_state = ProfileCollectionState.COLLECT_DETAIL
            
            return AgentResponse(
                message=ProfileQuestionBank.TRANSITION_PHRASES["to_detail"],
                state_update={
                    "collection_state": self.profile_data.collection_state.value,
                    "collected_fields": self.profile_data.collected_fields,
                },
                is_profile_collection=True,
                next_question=ProfileQuestionBank.DETAIL_QUESTIONS["family_status"]["question"],
            )
    
    async def _handle_collect_detail(self, user_input: str) -> AgentResponse:
        """处理详细信息收集"""
        # 解析用户输入，更新画像数据
        extracted_info = await self._extract_profile_field(user_input)
        
        # 更新画像数据
        if extracted_info:
            for field, value in extracted_info.items():
                setattr(self.profile_data, field, value)
                self.profile_data.collected_fields.append(field)
        
        # 确定下一个需要收集的字段
        next_field = self._get_next_required_field(
            ProfileQuestionBank.DETAIL_QUESTIONS,
            self.profile_data.collected_fields
        )
        
        if next_field:
            # 继续收集详细信息
            return AgentResponse(
                message="",
                state_update={
                    "collection_state": self.profile_data.collection_state.value,
                    "collected_fields": self.profile_data.collected_fields,
                },
                is_profile_collection=True,
                next_question=ProfileQuestionBank.DETAIL_QUESTIONS[next_field]["question"],
            )
        else:
            # 详细信息收集完成，进入主对话
            self.profile_data.collection_state = ProfileCollectionState.READY
            
            # 保存用户画像
            await self._save_profile_data()
            
            return AgentResponse(
                message=ProfileQuestionBank.TRANSITION_PHRASES["to_ready"],
                state_update={
                    "collection_state": self.profile_data.collection_state.value,
                    "collected_fields": self.profile_data.collected_fields,
                },
                is_profile_collection=False,
            )
    
    async def _extract_profile_field(self, user_input: str) -> Optional[Dict[str, Any]]:
        """从用户输入中提取画像字段"""
        # 简化实现，实际应该使用LLM提取结构化信息
        return None
    
    def _get_next_required_field(self, questions: Dict[str, Dict], collected_fields: List[str]) -> Optional[str]:
        """获取下一个需要收集的字段"""
        for field, question_info in questions.items():
            if not question_info.get("optional", False) and field not in collected_fields:
                return field
        return None
    
    async def _save_profile_data(self) -> None:
        """保存用户画像数据"""
        # 简化实现，实际应该保存到持久化存储
        pass
    
    async def _handle_session_time_up(self) -> AgentResponse:
        """处理会话时间到达"""
        logger.info(f"Session time up: {self.current_session.session_id}")
        
        self.event_bus.emit(EventType.SESSION_TERMINATED, {
            "session_id": self.current_session.session_id,
            "total_turns": self.current_session.turn_count,
        })
        
        # 获取结束引导内容
        end_guide_content = await self._generate_session_end_guide()
        
        # 更新状态为时间到
        self.current_session.current_state = StateType.HANDOFF
        
        return AgentResponse(
            message=end_guide_content.message,
            state_update=self.current_session.to_summary(),
            should_pause=True,
            pause_reason="session_time_up",
            is_end_guide=True,
            next_topic_hint=end_guide_content.next_topic,
        )
    
    async def _generate_session_end_guide(self) -> SessionEndGuideContent:
        """
        生成会话结束引导内容
        
        Returns:
            SessionEndGuideContent: 包含结束消息、下次主题、总结
        """
        # 调用 LLM 生成结束引导
        prompt = self._build_end_guide_prompt()
        
        result = await self.llm_service.invoke(
            template_name="session_end_guide",
            variables=prompt,
        )
        
        # 解析结果
        return SessionEndGuideContent(
            message=result["message"],
            summary=result["summary"],
            next_topic=result["next_topic"],
            collected_highlights=result["highlights"],
        )
    
    def _build_end_guide_prompt(self) -> dict:
        """构建结束引导 Prompt 变量"""
        # 获取本次会话收集的信息摘要
        collected_events = self.memory_manager.get_recent_events(
            session_id=self.current_session.session_id
        ) if self.memory_manager else []
        
        # 构建 Prompt 变量
        return {
            "session_duration": self.session_timing.duration_minutes,
            "total_turns": self.current_session.turn_count,
            "conversation_history": self._format_conversation_for_summary(),
            "collected_events": [e.title for e in collected_events],
            "next_phase_hint": self._get_next_phase_hint(),
            "elderly_title": self.current_session.user_preferences.get("title", "老人家"),
        }
    
    def _format_conversation_for_summary(self) -> str:
        """格式化对话历史用于总结"""
        turns = self.current_session.conversation_history[-5:]  # 最近5轮
        return "\n".join([
            f"用户: {t.user_input}\n助手: {t.agent_response}"
            for t in turns
        ])
    
    def _get_next_phase_hint(self) -> str:
        """获取下一阶段提示"""
        # 根据当前阶段决定下次从哪里继续
        current_phase = self.current_session.current_phase
        phase_order = [
            PhaseType.CHILDHOOD,
            PhaseType.YOUTH,
            PhaseType.MIDDLE_AGE,
            PhaseType.ELDERLY,
        ]
        
        if current_phase in phase_order:
            idx = phase_order.index(current_phase)
            if idx < len(phase_order) - 1:
                return f"下次我们继续聊聊{phase_order[idx + 1].value}时期的故事"
        
        return "下次我们继续探索您的人生故事"