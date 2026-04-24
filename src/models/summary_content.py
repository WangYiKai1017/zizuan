from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from .event_info import EventInfo
from .person_info import PersonInfo


class TimeMarker(BaseModel):
    """时间标记"""
    time: str                       # 时间点
    events: List[str]               # 相关事件ID
    phase: str                      # 人生阶段


class ThemeInfo(BaseModel):
    """主题信息"""
    theme: str                      # 主题名称
    related_events: List[str]       # 相关事件
    description: str                # 描述


class ExtractedInfo(BaseModel):
    """提取的信息汇总"""
    events: List[EventInfo] = []
    people: List[PersonInfo] = []
    time_markers: List[TimeMarker] = []
    themes: List[ThemeInfo] = []


class MemoryUpdatePlan(BaseModel):
    """记忆更新计划"""
    short_term_updates: Dict[str, Any] = {}
    long_term_files: List[str] = []          # 需要更新的文件路径
    profile_updates: Dict[str, Any] = {}


class SummaryContent(BaseModel):
    """
    归纳内容 - 结构化的归纳结果
    
    职责：
    - 封装内容归纳的完整结果
    - 指导记忆库更新
    
    使用场景：
    - ContentSummarizer.summarize() 的输出
    - MemoryManager 更新记忆的依据
    - HandoffPackage 的组成部分
    """
    
    summary_id: str = Field(..., description="归纳ID")
    session_id: str = Field(..., description="会话ID")
    turn_range: Tuple[int, int] = Field(..., description="覆盖的对话轮次范围")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    
    # 提取的信息
    extracted_info: ExtractedInfo = Field(default_factory=ExtractedInfo)
    
    # 记忆更新指令
    memory_updates: MemoryUpdatePlan = Field(default_factory=MemoryUpdatePlan)
    
    # 待处理问题
    pending_questions: List[str] = Field(default_factory=list)
    
    # 交接状态
    handoff_ready: bool = Field(default=False)
    handoff_reason: Optional[str] = Field(default=None)