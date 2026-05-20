# 开发故事卡 - Task 014: Agent 服务化

> 任务编号：Task-014  
> 优先级：P0  
> 依赖：Task-013（InterviewSessionAgent）、Task-014 知识库整理 Agent、传记大纲/写作 Agent  
> 预计工时：3-4 天

---

## 一、任务概述

### 1.1 核心目标

将现有 4 个 Agent（采访、知识库整理、传记大纲、传记写作）+ 文件服务封装为 FastAPI HTTP/SSE 后端，统一对外暴露 RESTful 接口，替代当前以测试脚本直接调用 Agent 的方式。

### 1.2 被替代的测试入口脚本

| 脚本 | 对应 Agent |
|------|-----------|
| `integration_test_new_user.py` | InterviewSessionAgent |
| `test_kb_organizer_agent.py` | KBOrganizerAgent |
| `test_biography_outline_agent.py` | BiographyOutlineAgent |
| `test_biography_writing_agent.py` | BiographyWritingAgent |

服务化后，上述脚本功能由 HTTP/SSE 接口完全覆盖。

### 1.3 架构定位

```
┌──────────────────────────────────────────────────────────────┐
│                     FastAPI Application                        │
│                                                                │
│  ┌────────────┐  ┌────────────────┐  ┌────────────────────┐  │
│  │  Routes    │  │ SessionManager │  │   SSEEmitter       │  │
│  │ (5 groups) │  │  (singleton)   │  │  (streaming helper)│  │
│  └─────┬──────┘  └───────┬────────┘  └─────────┬──────────┘  │
│        │                  │                      │             │
│        ▼                  ▼                      ▼             │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                    Agent Runners                          │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │  │
│  │  │Interview │ │KBOrganizer│ │ Outline  │ │ Writing  │   │  │
│  │  │ Runner   │ │  Runner   │ │  Runner  │ │  Runner  │   │  │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘   │  │
│  └───────┼─────────────┼────────────┼────────────┼─────────┘  │
│          ▼             ▼            ▼            ▼             │
│  ┌───────────────────────────────────────────────────────────┐│
│  │              Existing Agent Internals (不修改)              ││
│  │  InterviewSessionAgent / KBOrganizerAgent /                ││
│  │  BiographyOutlineAgent / BiographyWritingAgent             ││
│  └───────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

---

## 二、设计约束

### 2.1 核心约束

1. **统一 SSE 流式输出**：所有 Agent 执行过程通过 SSEEmitter 抽象统一推送事件
2. **SessionManager 全局单例**：按 `user_id` 追踪活跃 Agent，强制同一用户同一时刻只能有一个 Agent 在运行
3. **不修改现有 Agent 内部逻辑**：Runner 作为外部包装层衔接 Agent 与 HTTP 层
4. **框架选型**：FastAPI + sse-starlette + uvicorn

### 2.2 Agent 类型区分

| Agent | 运行模式 | 并发规则 | 会话管理 |
|-------|---------|---------|---------|
| 采访 Agent | 交互式（持久会话） | 每用户一个 session，重复 start 返回已有 session_id | SessionManager 持有 Agent 实例 |
| 知识库整理 Agent | 任务式（一次性） | 执行期间锁定，完成后释放 | 无状态 |
| 传记大纲 Agent | 任务式（一次性） | 执行期间锁定，完成后释放 | 无状态 |
| 传记写作 Agent | 任务式（一次性） | 执行期间锁定，完成后释放 | 无状态 |

### 2.3 互斥规则

- 同一 `user_id` 同时只能运行 **一种** Agent
- 若 Interview Agent 正在活跃，启动 KB Organizer 将返回 `409 TASK_ALREADY_RUNNING`
- 若 Interview Agent 已有 session，再次调用 `/api/interview/start` 返回已有 `session_id`（幂等）

---

## 三、目录结构

```
src/service/
├── __init__.py
├── app.py                    # FastAPI app factory, CORS, lifespan
├── session_manager.py        # Global singleton: user→active agent tracking
├── sse_response.py           # Unified SSE streaming helper
├── routes/
│   ├── __init__.py
│   ├── interview.py          # /api/interview/* endpoints
│   ├── kb_organizer.py       # /api/kb-organizer/* endpoints
│   ├── biography_outline.py  # /api/biography/outline/* endpoints
│   ├── biography_writing.py  # /api/biography/writing/* endpoints
│   └── files.py              # /api/files/* endpoints
├── schemas/
│   ├── __init__.py
│   └── requests.py           # Pydantic request/response models
└── agent_runners/
    ├── __init__.py
    ├── base_runner.py         # Abstract base: SSE event emitter
    ├── interview_runner.py    # Wraps InterviewSessionAgent
    ├── kb_organizer_runner.py # Wraps KBOrganizerAgent
    ├── outline_runner.py      # Wraps BiographyOutlineAgent
    └── writing_runner.py      # Wraps BiographyWritingAgent
```

---

## 四、核心类设计

### 4.1 SessionManager（全局单例）

```python
# src/service/session_manager.py

from enum import Enum
from typing import Dict, Optional, Tuple
import uuid
from datetime import datetime


class AgentType(str, Enum):
    """Agent 类型枚举"""
    INTERVIEW = "interview"
    KB_ORGANIZER = "kb_organizer"
    BIOGRAPHY_OUTLINE = "biography_outline"
    BIOGRAPHY_WRITING = "biography_writing"


class SessionInfo:
    """会话信息"""
    session_id: str
    agent_type: AgentType
    user_id: str
    started_at: datetime
    agent_instance: Any  # 持有 Runner 或 Agent 实例（仅 Interview）


class SessionManager:
    """
    全局会话管理器（单例）
    
    职责：
    - 维护 user_id → active session 映射
    - 强制互斥：同一用户同时只能运行一个 Agent
    - Interview 幂等：重复 start 返回已有 session
    
    并发安全：
    - 使用 asyncio.Lock 保证原子性
    """
    
    _instance: Optional["SessionManager"] = None
    
    @classmethod
    def get_instance(cls) -> "SessionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._active_sessions: Dict[str, SessionInfo] = {}  # user_id -> SessionInfo
        self._lock: asyncio.Lock = asyncio.Lock()

    async def acquire(
        self, user_id: str, agent_type: AgentType
    ) -> Tuple[str, bool]:
        """
        尝试为用户获取 Agent 执行权
        
        Returns:
            (session_id, is_new) - session_id 和是否为新创建
            
        Raises:
            ConflictError: 另一种 Agent 正在运行
        """
        async with self._lock:
            existing = self._active_sessions.get(user_id)
            
            if existing is not None:
                if existing.agent_type == agent_type == AgentType.INTERVIEW:
                    # Interview 幂等：返回已有 session
                    return existing.session_id, False
                else:
                    # 冲突：另一个 Agent 正在运行
                    raise ConflictError(
                        f"用户 {user_id} 当前有 {existing.agent_type.value} 任务正在运行"
                    )
            
            # 创建新 session
            session_id = self._generate_session_id()
            self._active_sessions[user_id] = SessionInfo(
                session_id=session_id,
                agent_type=agent_type,
                user_id=user_id,
                started_at=datetime.now(),
            )
            return session_id, True

    async def release(self, user_id: str, session_id: str) -> None:
        """释放用户的 Agent 执行权"""
        async with self._lock:
            existing = self._active_sessions.get(user_id)
            if existing and existing.session_id == session_id:
                del self._active_sessions[user_id]

    def get_active_agent(self, user_id: str) -> Optional[AgentType]:
        """查询用户当前活跃的 Agent 类型"""
        existing = self._active_sessions.get(user_id)
        return existing.agent_type if existing else None

    def _generate_session_id(self) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = uuid.uuid4().hex[:6]
        return f"sess_{ts}_{suffix}"
```

### 4.2 SSEEmitter

```python
# src/service/sse_response.py

from typing import AsyncGenerator, Any
from datetime import datetime
import json
import asyncio


class SSEEmitter:
    """
    统一 SSE 事件发射器
    
    职责：
    - 提供标准化的事件推送接口
    - 所有 data payload 自动注入 timestamp
    - 支持 keepalive 心跳
    - 支持错误事件和终止事件
    
    使用方式：
        emitter = SSEEmitter()
        # 在 runner 中调用：
        await emitter.emit("task_progress", {"task_id": "001", ...})
        await emitter.emit_done("任务完成")
        # 在 route 中返回：
        return EventSourceResponse(emitter.stream())
    """

    def __init__(self, keepalive_interval: int = 15):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._keepalive_interval = keepalive_interval
        self._closed = False

    async def emit(self, event: str, data: dict) -> None:
        """发送一个 SSE 事件，自动注入 timestamp"""
        data["timestamp"] = datetime.now().isoformat()
        await self._queue.put((event, json.dumps(data, ensure_ascii=False)))

    async def emit_error(
        self, code: str, message: str, recoverable: bool = False
    ) -> None:
        """发送错误事件"""
        await self.emit("error", {
            "code": code,
            "message": message,
            "recoverable": recoverable,
        })

    async def emit_done(self, message: str = "完成") -> None:
        """发送结束事件并关闭流"""
        await self.emit("done", {"message": message})
        self._closed = True

    async def stream(self) -> AsyncGenerator[str, None]:
        """生成 SSE 文本流（供 EventSourceResponse 消费）"""
        while not self._closed:
            try:
                event, data = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self._keepalive_interval
                )
                yield f"event: {event}\ndata: {data}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
        
        # 排空剩余事件
        while not self._queue.empty():
            event, data = self._queue.get_nowait()
            yield f"event: {event}\ndata: {data}\n\n"
```

### 4.3 BaseAgentRunner（抽象基类）

```python
# src/service/agent_runners/base_runner.py

from abc import ABC, abstractmethod


class BaseAgentRunner(ABC):
    """
    Agent Runner 抽象基类
    
    职责：
    - 统一 Runner 接口
    - 持有 user_id、session_id、emitter 引用
    - 子类实现 run() 方法包装具体 Agent 调用
    """

    def __init__(self, user_id: str, session_id: str, emitter: SSEEmitter):
        self.user_id = user_id
        self.session_id = session_id
        self.emitter = emitter

    @abstractmethod
    async def run(self) -> None:
        """
        执行 Agent 任务
        
        实现要求：
        - 在执行过程中通过 self.emitter.emit() 推送进度事件
        - 正常结束时调用 self.emitter.emit_done()
        - 异常时调用 self.emitter.emit_error()
        """
        ...
```

### 4.4 Agent Runners 概要

```python
# src/service/agent_runners/interview_runner.py

class InterviewRunner(BaseAgentRunner):
    """
    采访 Agent Runner
    
    特殊性：
    - 持有 InterviewSessionAgent 实例（持久化在 SessionManager 中）
    - start() 启动会话，emit session_started + agent_message
    - handle_message() 处理单条消息，emit agent_message / phase_changed
    - end() 结束会话，释放 session
    """
    
    async def start(self) -> None: ...
    async def handle_message(self, message: str) -> None: ...
    async def end(self) -> dict: ...
    async def run(self) -> None:
        """Interview runner 不使用 run()，使用 start/handle_message/end"""
        raise NotImplementedError("Use start/handle_message/end instead")


# src/service/agent_runners/kb_organizer_runner.py

class KBOrganizerRunner(BaseAgentRunner):
    """
    知识库整理 Agent Runner
    
    流程：
    1. emit task_started
    2. 实例化 KBOrganizerAgent
    3. 调用 agent.run()，通过回调/轮询推送 task_progress
    4. emit task_completed / failed
    5. emit done
    """
    
    async def run(self) -> None: ...


# src/service/agent_runners/outline_runner.py

class OutlineRunner(BaseAgentRunner):
    """传记大纲 Agent Runner"""
    async def run(self) -> None: ...


# src/service/agent_runners/writing_runner.py

class WritingRunner(BaseAgentRunner):
    """传记写作 Agent Runner"""
    async def run(self) -> None: ...
```

---

## 五、接口清单

参照 `API接口文档.md`，共计 15 个端点，分布于 5 个路由组：

### 5.1 采访 Agent（/api/interview/*）

| 方法 | 路径 | 响应类型 | 说明 |
|------|------|---------|------|
| POST | `/api/interview/start` | SSE | 启动会话 |
| POST | `/api/interview/message` | SSE | 发送消息 |
| POST | `/api/interview/end` | JSON | 结束会话 |
| GET | `/api/interview/status/{user_id}/{session_id}` | JSON | 获取会话状态 |

### 5.2 知识库整理 Agent（/api/kb-organizer/*）

| 方法 | 路径 | 响应类型 | 说明 |
|------|------|---------|------|
| POST | `/api/kb-organizer/run` | SSE | 启动整理任务 |
| GET | `/api/kb-organizer/result/{user_id}` | JSON | 获取整理结果 |

### 5.3 传记大纲 Agent（/api/biography/outline/*）

| 方法 | 路径 | 响应类型 | 说明 |
|------|------|---------|------|
| POST | `/api/biography/outline/generate` | SSE | 生成/更新大纲 |
| GET | `/api/biography/outline/{user_id}` | JSON | 获取当前大纲 |
| PUT | `/api/biography/outline/{user_id}/chapters/{chapter_id}/confirm` | JSON | 确认章节 |

### 5.4 传记写作 Agent（/api/biography/writing/*）

| 方法 | 路径 | 响应类型 | 说明 |
|------|------|---------|------|
| POST | `/api/biography/writing/run` | SSE | 启动写作任务 |
| GET | `/api/biography/writing/{user_id}/chapters` | JSON | 获取章节列表 |
| GET | `/api/biography/writing/{user_id}/full` | JSON | 获取完整传记 |

### 5.5 文件服务（/api/files/*）

| 方法 | 路径 | 响应类型 | 说明 |
|------|------|---------|------|
| GET | `/api/files/{user_id}` | JSON | 列出根目录 |
| GET | `/api/files/{user_id}/tree` | JSON | 获取完整目录树 |
| GET | `/api/files/{user_id}/{path:path}` | JSON | 获取文件/目录内容 |

---

## 六、请求/响应模型（Schemas）

```python
# src/service/schemas/requests.py

from pydantic import BaseModel, Field, field_validator
import re


class UserIdRequest(BaseModel):
    """通用请求：仅包含 user_id"""
    user_id: str = Field(..., min_length=3, max_length=50)
    
    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError("user_id 仅允许字母、数字、下划线")
        return v


class InterviewStartRequest(UserIdRequest):
    """采访启动请求"""
    pass


class InterviewMessageRequest(UserIdRequest):
    """采访消息请求"""
    session_id: str
    message: str = Field(..., min_length=1, max_length=5000)


class InterviewEndRequest(UserIdRequest):
    """采访结束请求"""
    session_id: str


class ChapterConfirmRequest(BaseModel):
    """章节确认请求（可选）"""
    notes: str | None = None
```

---

## 七、App 组装与入口

```python
# src/service/app.py

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.service.session_manager import SessionManager
from src.service.routes import (
    interview, kb_organizer, biography_outline, biography_writing, files
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：初始化 SessionManager"""
    SessionManager.get_instance()
    yield
    # cleanup if needed


def create_app() -> FastAPI:
    app = FastAPI(
        title="老人自传写作 Agent 服务",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 注册路由
    app.include_router(interview.router, prefix="/api/interview", tags=["采访"])
    app.include_router(kb_organizer.router, prefix="/api/kb-organizer", tags=["知识库整理"])
    app.include_router(biography_outline.router, prefix="/api/biography/outline", tags=["传记大纲"])
    app.include_router(biography_writing.router, prefix="/api/biography/writing", tags=["传记写作"])
    app.include_router(files.router, prefix="/api/files", tags=["文件服务"])
    
    return app


# run_server.py (项目根目录)
# import uvicorn
# from src.service.app import create_app
# app = create_app()
# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## 八、开发任务分解

### 8.1 Phase 1: 基础设施（Day 1）

| 序号 | 任务 | 产出 |
|------|------|------|
| 1.1 | 更新 `requirements.txt` 添加 fastapi, sse-starlette, uvicorn | 依赖文件 |
| 1.2 | 实现 `src/service/sse_response.py` | SSEEmitter 类 |
| 1.3 | 实现 `src/service/session_manager.py` | SessionManager 单例 |
| 1.4 | 实现 `src/service/schemas/requests.py` | 请求模型 |
| 1.5 | 编写 session_manager 单元测试 | 互斥/幂等验证 |
| 1.6 | 编写 sse_response 单元测试 | 事件格式验证 |

### 8.2 Phase 2: 文件服务（Day 1-2）

| 序号 | 任务 | 产出 |
|------|------|------|
| 2.1 | 实现 `src/service/routes/files.py` | 3 个文件端点 |
| 2.2 | 编写文件服务单元测试 | 目录树、文件读取 |

### 8.3 Phase 3: Agent Runners（Day 2-3）

| 序号 | 任务 | 产出 |
|------|------|------|
| 3.1 | 实现 `base_runner.py` | 抽象基类 |
| 3.2 | 实现 `interview_runner.py` | 采访 Runner |
| 3.3 | 实现 `kb_organizer_runner.py` | 知识库整理 Runner |
| 3.4 | 实现 `outline_runner.py` | 大纲 Runner |
| 3.5 | 实现 `writing_runner.py` | 写作 Runner |

### 8.4 Phase 4: 路由处理器（Day 3）

| 序号 | 任务 | 产出 |
|------|------|------|
| 4.1 | 实现 `routes/interview.py` | 4 个采访端点 |
| 4.2 | 实现 `routes/kb_organizer.py` | 2 个整理端点 |
| 4.3 | 实现 `routes/biography_outline.py` | 3 个大纲端点 |
| 4.4 | 实现 `routes/biography_writing.py` | 3 个写作端点 |

### 8.5 Phase 5: 组装与测试（Day 3-4）

| 序号 | 任务 | 产出 |
|------|------|------|
| 5.1 | 实现 `src/service/app.py` | App Factory |
| 5.2 | 创建 `run_server.py` 入口 | 服务启动脚本 |
| 5.3 | 编写路由层集成测试 | 全端点覆盖 |
| 5.4 | 端到端验证 | 15 个接口全部响应正确 |

---

## 九、验收标准

### 9.1 功能验收

- [ ] 所有 15 个端点按 `API接口文档.md` 正确响应
- [ ] SessionManager 正确阻止同一用户并发运行不同 Agent（返回 409）
- [ ] Interview Agent 重复 start 返回已有 session_id（幂等）
- [ ] SSE 事件格式正确（`event:` + `data:` + 空行分隔）
- [ ] 所有 SSE data 载荷包含 `timestamp` 字段
- [ ] 心跳机制正常（15 秒无事件发送 `:keepalive`）
- [ ] 文件服务正确返回目录结构与文件内容
- [ ] 错误响应符合通用错误格式规范

### 9.2 代码质量验收

- [ ] 不修改现有 Agent 内部代码（`src/agents/` 下文件无改动）
- [ ] 所有新代码位于 `src/service/` 目录
- [ ] 类型注解完整，Pydantic 模型规范
- [ ] 每个文件 ≤ 250 行
- [ ] 异步代码无阻塞调用（Agent 执行在后台任务中）
- [ ] 依赖注入清晰，无隐式全局状态（SessionManager 单例除外）

### 9.3 测试验收

- [ ] `session_manager.py` 单元测试覆盖：acquire / release / 互斥 / 幂等
- [ ] `sse_response.py` 单元测试覆盖：emit / emit_error / emit_done / stream 格式
- [ ] 文件服务路由测试覆盖：目录列表 / 文件读取 / 目录树 / 404 处理
- [ ] 服务使用 `python run_server.py` 正常启动并接受请求

### 9.4 启动验证

```bash
# 启动服务
python run_server.py

# 验证健康检查
curl http://localhost:8000/docs  # Swagger UI 正常展示

# 验证文件服务
curl http://localhost:8000/api/files/test_user002

# 验证 SSE 流
curl -X POST http://localhost:8000/api/interview/start \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test_user002"}'
```

---

## 十、注意事项

### 10.1 SSE 连接管理

- 客户端断开连接时，Runner 应能感知并释放 SessionManager 中的 session
- 使用 `request.is_disconnected()` 检测客户端断连
- 任务式 Agent 断连后继续执行完毕（后台完成，结果可通过 GET 接口获取）

### 10.2 Agent 执行模式

- **交互式（Interview）**：Runner 实例持久化在 SessionManager 中，每次 `/message` 调用 `handle_message()`
- **任务式（其他三个）**：收到请求后启动后台 asyncio.Task 执行 Runner.run()，通过 SSE 推送进度

### 10.3 错误处理策略

| 场景 | 处理方式 |
|------|---------|
| user_id 格式非法 | 400 INVALID_REQUEST |
| 知识库不存在 | 404 USER_NOT_FOUND |
| 另一个 Agent 运行中 | 409 TASK_ALREADY_RUNNING |
| LLM 调用超时 | SSE emit_error + 503 |
| Agent 内部异常 | SSE emit_error + 自动 release session |

### 10.4 并发安全

- SessionManager 所有状态修改操作必须在 `asyncio.Lock` 保护下执行
- SSEEmitter 的 `asyncio.Queue` 天然支持单生产者-单消费者模式
- 避免在路由层直接操作 Agent 实例，统一通过 Runner 间接调用

---

## 十一、依赖新增

```
# requirements.txt 新增
fastapi>=0.104.0
sse-starlette>=1.6.0
uvicorn[standard]>=0.24.0
```

---

## 十二、参考资源

| 资源 | 路径 | 用途 |
|------|------|------|
| API 接口文档 | `API接口文档.md` | 接口规范定义 |
| 采访 Agent | `src/agents/interview_session_agent.py` | Runner 包装对象 |
| 知识库整理 Agent | `src/agents/kb_organizer_agent.py` | Runner 包装对象 |
| 传记大纲 Agent | `src/agents/biography_outline_agent.py` | Runner 包装对象 |
| 传记写作 Agent | `src/agents/biography_writing_agent.py` | Runner 包装对象 |
| 测试知识库 | `knowledge_base/test_user002/` | 文件服务测试数据 |
| 现有故事卡 | `开发故事卡/Task-013-实现Agent服务主体.md` | 风格参考 |

---

**文档版本**：v1.0  
**创建日期**：2026-05-17  
**最后更新**：2026-05-17
