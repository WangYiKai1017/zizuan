"""Unit tests for SSE response formatting."""
import asyncio
import json
import pytest

from src.service.sse_response import SSEEvent, SSEEmitter


class TestSSEEvent:
    """Tests for SSEEvent formatting."""
    
    def test_format_basic_event(self):
        event = SSEEvent(event="task_started", data={"user_id": "test", "count": 3})
        formatted = event.format()
        
        assert formatted.startswith("event: task_started\n")
        assert "data: " in formatted
        assert formatted.endswith("\n\n")
        
        # Parse the data line
        lines = formatted.strip().split("\n")
        data_line = [l for l in lines if l.startswith("data: ")][0]
        data = json.loads(data_line[6:])
        assert data["user_id"] == "test"
        assert data["count"] == 3
    
    def test_format_chinese_content(self):
        event = SSEEvent(event="agent_message", data={"message": "你好，我是采访助手"})
        formatted = event.format()
        assert "你好，我是采访助手" in formatted
    
    def test_format_preserves_all_fields(self):
        data = {"a": 1, "b": "two", "c": [1, 2, 3], "d": {"nested": True}}
        event = SSEEvent(event="test", data=data)
        formatted = event.format()
        
        data_line = formatted.split("\n")[1]
        parsed = json.loads(data_line[6:])
        assert parsed == data


@pytest.mark.asyncio
class TestSSEEmitter:
    """Tests for SSEEmitter."""
    
    async def test_emit_and_stream(self):
        emitter = SSEEmitter()
        
        # Emit in background
        async def producer():
            await emitter.emit("start", {"msg": "hello"})
            await emitter.emit_done("finished")
        
        asyncio.create_task(producer())
        
        chunks = []
        async for chunk in emitter.stream():
            chunks.append(chunk)
        
        assert len(chunks) == 2
        assert "event: start" in chunks[0]
        assert "event: done" in chunks[1]
    
    async def test_emit_adds_timestamp(self):
        emitter = SSEEmitter()
        
        async def producer():
            await emitter.emit("test", {"value": 42})
            await emitter.emit_done()
        
        asyncio.create_task(producer())
        
        chunks = []
        async for chunk in emitter.stream():
            chunks.append(chunk)
        
        # First chunk should have timestamp
        data_line = chunks[0].split("\n")[1]
        data = json.loads(data_line[6:])
        assert "timestamp" in data
        assert data["value"] == 42
    
    async def test_emit_preserves_existing_timestamp(self):
        emitter = SSEEmitter()
        
        async def producer():
            await emitter.emit("test", {"timestamp": "custom_time", "x": 1})
            await emitter.emit_done()
        
        asyncio.create_task(producer())
        
        chunks = []
        async for chunk in emitter.stream():
            chunks.append(chunk)
        
        data_line = chunks[0].split("\n")[1]
        data = json.loads(data_line[6:])
        assert data["timestamp"] == "custom_time"
    
    async def test_emit_error(self):
        emitter = SSEEmitter()
        
        async def producer():
            await emitter.emit_error("TEST_ERROR", "Something went wrong", recoverable=True)
            await emitter.emit_done()
        
        asyncio.create_task(producer())
        
        chunks = []
        async for chunk in emitter.stream():
            chunks.append(chunk)
        
        assert "event: error" in chunks[0]
        data_line = chunks[0].split("\n")[1]
        data = json.loads(data_line[6:])
        assert data["code"] == "TEST_ERROR"
        assert data["message"] == "Something went wrong"
        assert data["recoverable"] is True
    
    async def test_emit_after_done_ignored(self):
        emitter = SSEEmitter()
        
        async def producer():
            await emitter.emit("first", {"n": 1})
            await emitter.emit_done("end")
            await emitter.emit("ignored", {"n": 2})  # Should be ignored
        
        asyncio.create_task(producer())
        
        chunks = []
        async for chunk in emitter.stream():
            chunks.append(chunk)
        
        # Only "first" and "done" should appear
        assert len(chunks) == 2
