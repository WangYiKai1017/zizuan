from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional
from .event_info import EventInfo


class Entity(BaseModel):
    """实体"""
    type: str       # person/place/time/organization
    name: str
    metadata: dict = {}


class ConversationTurn(BaseModel):
    """
    对话轮次 - 记录单轮对话的完整信息
    
    职责：
    - 记录用户输入和Agent回复
    - 追踪提取的实体和事件
    - 关联情绪状态
    
    使用场景：
    - SessionState.conversation_history 的元素
    - EmotionDetector 的输入
    - ContentSummarizer 的输入
    """
    
    turn_id: int = Field(..., description="轮次ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    
    # 用户输入
    user_input: str = Field(..., description="用户输入文本")
    
    # Agent回复
    agent_response: Optional[str] = Field(default=None, description="Agent回复文本")
    
    # 提取的信息
    extracted_entities: List[Entity] = Field(default_factory=list, description="提取的实体")
    extracted_events: List[EventInfo] = Field(default_factory=list, description="提取的事件预览")
    
    # 情绪
    emotion: Optional[str] = Field(default=None, description="情绪类型")
    
    # 来源追溯
    source_files_referenced: List[str] = Field(
        default_factory=list,
        description="引用的记忆库文件"
    )
    
    # 元数据
    metadata: dict = Field(default_factory=dict, description="额外元数据")