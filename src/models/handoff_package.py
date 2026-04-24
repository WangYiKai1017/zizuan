from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, List
from .event_info import EventInfo
from .person_info import PersonInfo
from .summary_content import TimeMarker, ThemeInfo


class ProgressInfo(BaseModel):
    """阶段进度信息"""
    coverage: float = 0.0
    events: int = 0
    people: int = 0


class SessionSummary(BaseModel):
    """会话摘要"""
    session_id: str
    total_turns: int
    duration_minutes: float
    strategy_used: str


class CollectedData(BaseModel):
    """采集数据"""
    events: List[EventInfo] = []
    people: List[PersonInfo] = []
    timeline: List[TimeMarker] = []
    themes: List[ThemeInfo] = []


class HandoffPackage(BaseModel):
    """
    交接包 - 传递给下游Agent的数据包
    
    职责：
    - 封装完整的采集结果
    - 记录采集进度和提示
    
    使用场景：
    - ConversationOrchestrator.terminate_session() 的输出
    - 传递给下游 Agent-B（结构化内容整理层）
    """
    
    handoff_id: str = Field(..., description="交接ID")
    from_agent: str = Field(default="Agent-A", description="来源Agent")
    to_agent: str = Field(default="Agent-B", description="目标Agent")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    
    # 会话信息
    session_info: SessionSummary
    
    # 采集进度
    collection_progress: Dict[str, ProgressInfo] = Field(default_factory=dict)
    
    # 采集数据
    collected_data: CollectedData = Field(default_factory=CollectedData)
    
    # 原始对话文件路径
    raw_conversations_path: str = Field(default="", description="原始对话记录文件路径")
    
    # 待处理问题
    pending_questions: List[str] = Field(default_factory=list)
    
    # 给下游的提示
    notes_for_agent_b: List[str] = Field(default_factory=list)