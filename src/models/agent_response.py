from pydantic import BaseModel, Field
from typing import Dict, Any, Optional


class AgentResponse(BaseModel):
    """
    Agent响应 - 单轮对话的响应结构
    
    职责：
    - 封装Agent的响应信息
    - 包含状态更新
    
    使用场景：
    - ConversationOrchestrator.process_turn() 的返回值
    - 返回给上层调用者
    """
    
    message: str = Field(..., description="Agent回复消息")
    state_update: Dict[str, Any] = Field(default_factory=dict, description="状态更新摘要")
    should_pause: bool = Field(default=False, description="是否应该暂停")
    pause_reason: Optional[str] = Field(default=None, description="暂停原因")
    handoff_triggered: bool = Field(default=False, description="是否触发交接")