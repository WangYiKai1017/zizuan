"""Unified SSE streaming response abstraction.

All agent runners use SSEEmitter to emit events. No agent directly formats SSE text.
"""
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional


@dataclass
class SSEEvent:
    """A single SSE event."""
    event: str
    data: Dict[str, Any]
    
    def format(self) -> str:
        """Format as SSE wire protocol."""
        return f"event: {self.event}\ndata: {json.dumps(self.data, ensure_ascii=False, default=str)}\n\n"


class SSEEmitter:
    """Async SSE event emitter.
    
    Usage:
        emitter = SSEEmitter()
        # In the runner coroutine:
        await emitter.emit("task_started", {"user_id": "xxx", ...})
        await emitter.emit("completed", {...})
        await emitter.emit_done("任务完成")
        
        # In the route handler, return EventSourceResponse(emitter.stream())
    """
    
    def __init__(self):
        self._queue: asyncio.Queue[Optional[SSEEvent]] = asyncio.Queue()
        self._closed = False
    
    async def emit(self, event: str, data: Dict[str, Any]) -> None:
        """Emit an SSE event. Automatically adds timestamp if not present."""
        if self._closed:
            return
        if "timestamp" not in data:
            data["timestamp"] = datetime.now(timezone.utc).astimezone().isoformat()
        await self._queue.put(SSEEvent(event=event, data=data))
    
    async def emit_error(self, code: str, message: str, recoverable: bool = False) -> None:
        """Emit an error event."""
        await self.emit("error", {
            "code": code,
            "message": message,
            "recoverable": recoverable,
        })
    
    async def emit_done(self, message: str = "流结束") -> None:
        """Emit the done event and close the stream."""
        await self.emit("done", {"message": message})
        self._closed = True
        await self._queue.put(None)  # Sentinel to end stream
    
    async def stream(self) -> AsyncGenerator[str, None]:
        """Yield formatted SSE strings. Use with EventSourceResponse or StreamingResponse."""
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event.format()
