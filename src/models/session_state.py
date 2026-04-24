from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, List, Optional, Any
from src.enums import StateType, PhaseType, StrategyType, EmotionType
from .conversation_turn import ConversationTurn
from .emotion_result import EmotionResult


class TopicInfo(BaseModel):
    """当前话题信息"""
    type: str                           # event/person/theme
    name: str                           # 话题名称
    start_turn: int                     # 开始轮次
    depth: int = 0                      # 挖掘深度


class EmotionState(BaseModel):
    """情绪状态"""
    emotion_type: EmotionType = EmotionType.NEUTRAL
    intensity: str = "low"
    last_change_turn: int = 0


class SessionState(BaseModel):
    """
    会话状态 - 贯穿整个会话生命周期的核心数据对象
    
    职责：
    - 记录当前会话的所有状态信息
    - 追踪对话进度和覆盖率
    - 管理采集的事件和人物
    
    使用场景：
    - ConversationOrchestrator 持有并更新
    - 所有Service对象读取状态信息
    - 暂停/恢复时持久化/反序列化
    """
    
    # 基本信息
    session_id: str = Field(..., description="会话唯一标识")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    last_activity: datetime = Field(default_factory=datetime.now, description="最后活动时间")
    
    # 状态
    current_state: StateType = Field(default=StateType.INIT, description="当前对话状态")
    current_phase: PhaseType = Field(default=PhaseType.CHILDHOOD, description="当前人生阶段")
    strategy: StrategyType = Field(default=StrategyType.SPARKLE_FIRST, description="当前采访策略")
    
    # 进度
    turn_count: int = Field(default=0, description="对话轮数")
    coverage: Dict[PhaseType, float] = Field(
        default_factory=lambda: {
            PhaseType.CHILDHOOD: 0.0,
            PhaseType.YOUTH: 0.0,
            PhaseType.YOUNG_ADULT: 0.0,
            PhaseType.MIDDLE_AGE: 0.0,
            PhaseType.ELDERLY: 0.0,
        },
        description="各阶段覆盖率"
    )
    
    # 采集内容
    collected_events: List[str] = Field(default_factory=list, description="已收集事件ID列表")
    collected_people: List[str] = Field(default_factory=list, description="已收集人物ID列表")
    
    # 当前话题
    current_topic: Optional[TopicInfo] = Field(default=None, description="当前话题")
    
    # 情绪状态
    emotion_state: EmotionState = Field(default_factory=EmotionState, description="情绪状态")
    
    # 待处理
    pending_questions: List[str] = Field(default_factory=list, description="待追问问题列表")
    
    # 对话历史
    conversation_history: List[ConversationTurn] = Field(
        default_factory=list,
        description="对话历史"
    )
    
    # 用户偏好
    user_preferences: Dict[str, Any] = Field(default_factory=dict, description="用户偏好")
    
    class Config:
        use_enum_values = True
    
    def add_turn(self, turn: ConversationTurn) -> None:
        """添加一轮对话"""
        self.conversation_history.append(turn)
        self.turn_count += 1
        self.last_activity = datetime.now()
    
    def update_coverage(self, phase: PhaseType, value: float) -> None:
        """更新覆盖率"""
        self.coverage[phase] = min(1.0, max(0.0, value))
    
    def mark_event_collected(self, event_id: str) -> None:
        """标记事件已采集"""
        if event_id not in self.collected_events:
            self.collected_events.append(event_id)
    
    def mark_person_collected(self, person_id: str) -> None:
        """标记人物已采集"""
        if person_id not in self.collected_people:
            self.collected_people.append(person_id)
    
    def push_pending_question(self, question: str) -> None:
        """添加待追问问题"""
        self.pending_questions.append(question)
    
    def pop_pending_question(self) -> Optional[str]:
        """获取并移除待追问问题"""
        return self.pending_questions.pop(0) if self.pending_questions else None
    
    def has_pending_questions(self) -> bool:
        """是否有待追问问题"""
        return len(self.pending_questions) > 0
    
    def update_from_emotion(self, emotion_result: EmotionResult) -> None:
        """从情绪结果更新状态"""
        self.emotion_state.emotion_type = emotion_result.emotion_type
        self.emotion_state.intensity = emotion_result.intensity
        self.emotion_state.last_change_turn = self.turn_count
    
    def to_summary(self) -> Dict[str, Any]:
        """生成状态摘要"""
        return {
            "session_id": self.session_id,
            "current_state": self.current_state,
            "current_phase": self.current_phase,
            "turn_count": self.turn_count,
            "coverage": self.coverage,
            "collected_events_count": len(self.collected_events),
            "collected_people_count": len(self.collected_people),
        }
    
    def get_recent_history(self, n: int = 5) -> List[ConversationTurn]:
        """获取最近n轮对话"""
        return self.conversation_history[-n:] if self.conversation_history else []