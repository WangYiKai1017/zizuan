"""Unified SSE streaming response abstraction.

All agent runners use SSEEmitter to emit events. No agent directly formats SSE text.
"""
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

from sse_starlette.event import JSONServerSentEvent


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
        self.emitted_count = 0
        self.sent_count = 0
        self._events: list[dict[str, Any]] = []
    
    async def emit(self, event: str, data: Dict[str, Any]) -> None:
        """Emit an SSE event. Automatically adds timestamp if not present."""
        if self._closed:
            return
        if "timestamp" not in data:
            data["timestamp"] = datetime.now(timezone.utc).astimezone().isoformat()
        sse_event = SSEEvent(event=event, data=data)
        self._events.append(self._event_snapshot(sse_event))
        await self._queue.put(sse_event)
        self.emitted_count += 1
    
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
    
    async def stream(self) -> AsyncGenerator[JSONServerSentEvent, None]:
        """Yield JSONServerSentEvent objects. Use with EventSourceResponse."""
        while True:
            event = await self._queue.get()
            if event is None:
                break
            self.sent_count += 1
            yield JSONServerSentEvent(data=event.data, event=event.event)

    @property
    def events(self) -> list[dict[str, Any]]:
        """Return emitted SSE events as JSON-serializable trace payloads."""
        return list(self._events)

    def trace_output(self, status: str, **extra: Any) -> dict[str, Any]:
        """Build route-level Langfuse output including all emitted SSE events."""
        output = {
            "status": status,
            "events_emitted": self.emitted_count,
            "events_sent": self.sent_count,
            "events": self.events,
        }
        output.update(extra)
        return output

    @staticmethod
    def _event_snapshot(event: SSEEvent) -> dict[str, Any]:
        return {
            "event": event.event,
            "data": json.loads(json.dumps(event.data, ensure_ascii=False, default=str)),
        }
