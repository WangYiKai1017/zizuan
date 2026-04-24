# src/core/event_bus.py
from typing import Callable, Dict, List, Any, Optional
from enum import Enum
import asyncio
import logging

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """事件类型"""
    # 对话事件
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    
    # 状态事件
    STATE_CHANGED = "state_changed"
    PHASE_CHANGED = "phase_changed"
    STRATEGY_CHANGED = "strategy_changed"
    
    # 记忆事件
    MEMORY_UPDATED = "memory_updated"
    EVENT_CREATED = "event_created"
    PERSON_CREATED = "person_created"
    
    # 情绪事件
    EMOTION_DETECTED = "emotion_detected"
    EMOTION_ALERT = "emotion_alert"
    
    # 交接事件
    HANDOFF_READY = "handoff_ready"
    HANDOFF_COMPLETED = "handoff_completed"
    
    # 会话事件
    SESSION_STARTED = "session_started"
    SESSION_PAUSED = "session_paused"
    SESSION_TERMINATED = "session_terminated"


class EventBus:
    """
    事件总线
    
    职责：
    - 发布/订阅模式的事件分发
    - 解耦组件间的通信
    - 支持异步处理
    
    使用场景：
    - ConversationOrchestrator 发布事件
    - ContentSummarizer 订阅事件触发归纳
    - 外部系统订阅事件进行监控
    """
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._async_subscribers: Dict[EventType, List[Callable]] = {}
    
    def subscribe(
        self,
        event_type: EventType,
        handler: Callable[[Any], None],
    ) -> None:
        """
        订阅事件（同步处理器）
        
        Args:
            event_type: 事件类型
            handler: 处理函数
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed to {event_type}: {handler.__name__}")
    
    def subscribe_async(
        self,
        event_type: EventType,
        handler: Callable[[Any], Any],
    ) -> None:
        """
        订阅事件（异步处理器）
        
        Args:
            event_type: 事件类型
            handler: 异步处理函数
        """
        if event_type not in self._async_subscribers:
            self._async_subscribers[event_type] = []
        self._async_subscribers[event_type].append(handler)
        logger.debug(f"Subscribed async to {event_type}: {handler.__name__}")
    
    def unsubscribe(
        self,
        event_type: EventType,
        handler: Callable,
    ) -> None:
        """取消订阅"""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h != handler
            ]
        if event_type in self._async_subscribers:
            self._async_subscribers[event_type] = [
                h for h in self._async_subscribers[event_type] if h != handler
            ]
    
    def emit(
        self,
        event_type: EventType,
        data: Any = None,
    ) -> None:
        """
        发布事件（同步）
        
        Args:
            event_type: 事件类型
            data: 事件数据
        """
        logger.debug(f"Emitting event: {event_type}")
        
        # 调用同步处理器
        if event_type in self._subscribers:
            for handler in self._subscribers[event_type]:
                try:
                    handler(data)
                except Exception as e:
                    logger.error(f"Event handler error: {e}")
        
        # 异步调用异步处理器
        if event_type in self._async_subscribers:
            for handler in self._async_subscribers[event_type]:
                asyncio.create_task(self._safe_async_call(handler, data))
    
    async def _safe_async_call(self, handler: Callable, data: Any) -> None:
        """安全调用异步处理器"""
        try:
            await handler(data)
        except Exception as e:
            logger.error(f"Async event handler error: {e}")
    
    async def emit_and_wait(
        self,
        event_type: EventType,
        data: Any = None,
    ) -> None:
        """
        发布事件并等待所有异步处理器完成
        
        Args:
            event_type: 事件类型
            data: 事件数据
        """
        logger.debug(f"Emitting event (waiting): {event_type}")
        
        # 调用同步处理器
        if event_type in self._subscribers:
            for handler in self._subscribers[event_type]:
                try:
                    handler(data)
                except Exception as e:
                    logger.error(f"Event handler error: {e}")
        
        # 等待所有异步处理器
        if event_type in self._async_subscribers:
            tasks = [
                self._safe_async_call(handler, data)
                for handler in self._async_subscribers[event_type]
            ]
            await asyncio.gather(*tasks)


# 全局事件总线
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取全局事件总线"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus