# 底层代码优化重构 Spec

**状态:** Draft  
**优先级:** High  
**预估工时:** 6-9 人天  
**分析日期:** 2026-05-10

---

## 1. 诊断概览

当前系统整体架构与 Harness 范式设计文档基本对齐，但实现层面存在 **7 项关键架构违规**、**12 项主要 OOP 设计问题** 和 **5 项性能瓶颈**。偏差主要为"增量性偏差"（未按规范执行），而非根本性架构断裂。

### 核心问题一览

| 问题 ID | 严重性 | 类型 | 涉及文件 | 摘要 |
|---------|--------|------|----------|------|
| CIRC-1 | CRITICAL | 循环依赖 | `storage/memory_repository.py` | Storage 层直接导入 Service 层 (KnowledgeBaseQuerier) |
| CIRC-2 | CRITICAL | 隐式全局状态 | 6+ 个 service 文件 | `llm_service or get_llm_service()` 全局单例滥用 |
| LAYER-1 | CRITICAL | 层级违规 | `agents/*.py` | Agent 层内部创建 Storage 层实例 |
| ABS-1 | MAJOR | 缺失抽象 | 所有 service 文件 | 无接口定义，无法替换实现 |
| ANEMIC-1 | MAJOR | 贫血模型 | `models/*.py` | 业务逻辑散落在各 service 中，model 只是数据容器 |
| DUP-1 | MAJOR | 功能重复 | MemoryRepository / MemoryManager / MemoryCacheTool / MemoryArchiveTool | 4 个类职责重叠 |
| DUP-2 | MAJOR | 初始化模式重复 | 7+ 文件 | 相同的 `__init__` 模式复制粘贴 |
| PERF-1 | MAJOR | 同步文件 I/O | `storage/markdown_file_manager.py` | 阻塞事件循环，违背 async 设计 |
| PERF-2 | MAJOR | N+1 文件读取 | `services/knowledge_base_querier.py` | 每次查询重复读取 markdown 文件 |
| PERF-3 | MAJOR | 无限流控制 | `services/llm_service.py` | 无 Token 预算/限流 |
| SPEC-1 | MAJOR | 缺失状态机 | `core/conversation_orchestrator.py` | Spec 要求的 FSM 未实现 |
| SPEC-2 | MAJOR | Prompt 分散 | `prompts/` + 根目录 `Prompts/` | 两个位置，未集中管理 |
| GOD-1 | MAJOR | 上帝类 | `core/conversation_orchestrator.py` (658 行) | 10+ 职责，应拆分 |

---

## 2. 当前架构 vs 理想架构

### 2.1 当前依赖图（有问题）

```
InterviewSessionAgent
├─ InterviewAgent
│  ├─ MemoryManager
│  │  ├─ MemoryRepository
│  │  │  ├─ MarkdownFileManager
│  │  │  ├─ KnowledgeBaseQuerier ◄── 循环依赖!
│  │  │  └─ LLMService (via get_llm_service) ◄── 隐式全局
│  │  ├─ LLMService (via get_llm_service)
│  ├─ QuestionGenerator
│  │  └─ LLMService (via get_llm_service)
│  ├─ MemoryCacheTool (自行创建)
│  ├─ KnowledgeQueryTool (自行创建)
│  ├─ MemoryArchiveTool (自行创建)
├─ ProfileCollectionAgent
│  ├─ MemoryManager (创建自己的实例) ◄── 重复实例
│  └─ LLMService (via get_llm_service)
└─ MemoryCacheTool, KnowledgeQueryTool (各自创建)

问题:
- 多个 MemoryManager 实例互不关联
- LLMService 通过全局单例被隐式依赖
- MemoryRepository ↔ KnowledgeBaseQuerier 循环引用
- Tools 自行创建依赖而非通过注入接收
```

### 2.2 理想依赖图（重构后）

```
InterviewSessionAgent (组合根 / Composition Root)
├─ LLMService (创建一次，向下注入)
├─ MarkdownFileManager (注入)
├─ MemoryRepository (注入，仅依赖 MarkdownFileManager)
├─ MemoryManager (注入，仅依赖 MemoryRepository + LLMService)
├─ InterviewOrchestrator (注入)
│  ├─ QuestionGenerator (注入 LLMService)
│  ├─ EmotionDetector (注入 LLMService)
│  └─ ContentSummarizer (注入 LLMService + MemoryManager)
├─ CollectionOrchestrator (注入)
│  └─ MemoryManager (共享)
└─ HandoffOrchestrator (注入)
   └─ MemoryManager (共享)

目标:
- 单一 LLMService 实例
- 所有依赖显式声明
- 无循环引用
- 易于测试 (mock)
- 易于替换实现
```

---

## 3. 分阶段重构计划

### Phase 1: 修复架构 (CRITICAL) — 2~3 天

#### Task R-1: 消除 MemoryRepository → Service 层循环依赖

**目标:** 使 MemoryRepository 成为纯存储层，不含任何 Service 层依赖

**当前问题:**
```python
# src/storage/memory_repository.py:9-11 (违规)
from src.services.knowledge_base_querier import KnowledgeBaseQuerier
from src.services.llm_service import get_llm_service
```

**重构方案:**
- 移除 MemoryRepository 中对 `KnowledgeBaseQuerier` 和 `get_llm_service` 的导入
- 将查询功能上移至 MemoryManager（Service 层调 Service 层是允许的）
- MemoryRepository 仅保留: 短期内存字典、长期文件读写、Profile JSON 读写
- 如需查询回调，通过构造函数注入 `Optional[Callable]` 而非直接依赖 Service 类

**验收标准:**
- `memory_repository.py` 的 import 中无 `src.services.*`
- 所有现有测试通过
- MemoryRepository 可独立实例化（无需 Service 层存在）

---

#### Task R-2: 消除隐式全局状态（LLMService 单例模式）

**目标:** 所有 Service 的 LLMService 依赖通过构造函数显式注入

**当前问题（6+ 文件重复此模式）:**
```python
def __init__(self, llm_service: LLMService = None):
    self.llm_service = llm_service or get_llm_service()  # 隐式全局
```

**重构方案:**
- LLMService 在构造函数中为 **必需参数**（非 Optional）
- 移除 `or get_llm_service()` 回退模式
- 在 Composition Root（InterviewSessionAgent）统一创建 LLMService 并向下传递
- `get_llm_service()` 仅在测试 fixture 或 CLI 入口使用

**涉及文件:**
- `src/services/emotion_detector.py`
- `src/services/question_generator.py`
- `src/services/content_summarizer.py`
- `src/services/memory_manager.py`
- `src/services/knowledge_base_querier.py`
- `src/tools/knowledge_query_tool.py`

**验收标准:**
- grep `get_llm_service` 在 `src/services/` 和 `src/agents/` 中只出现在 Composition Root
- 所有 Service 类的 `__init__` 中 `llm_service` 参数无默认值 None

---

#### Task R-3: 拆分 ConversationOrchestrator（上帝类）

**目标:** 将 658 行的上帝类拆分为 4~5 个单职责协调器

**当前问题:**
`conversation_orchestrator.py` 承担 10+ 职责：会话生命周期、状态机、情绪检测协调、记忆查询协调、内容摘要、问题生成、时间管理、交接准备、档案收集、事件总线发布

**重构方案:**

```
src/core/
├── session_orchestrator.py       # 会话生命周期 + 状态流转
├── interview_orchestrator.py     # 采访流程协调（问题生成 + 情绪检测 + 内容摘要）
├── collection_orchestrator.py    # 档案收集协调
├── handoff_orchestrator.py       # 交接准备
└── state_machine.py              # 正式的状态转移矩阵
```

**状态机设计（补全 Spec 要求）:**
```python
class StateMachine:
    TRANSITIONS = {
        StateType.INIT: [StateType.WARMUP, StateType.HANDOFF],
        StateType.WARMUP: [StateType.COLLECT, StateType.PAUSE],
        StateType.COLLECT: [StateType.DEEPEN, StateType.REDIRECT, StateType.PAUSE],
        StateType.DEEPEN: [StateType.COLLECT, StateType.REDIRECT, StateType.PAUSE],
        StateType.REDIRECT: [StateType.COLLECT, StateType.DEEPEN],
        StateType.PAUSE: [StateType.COLLECT, StateType.HANDOFF],
    }

    def can_transition(self, from_state: StateType, to_state: StateType) -> bool: ...
    def transition(self, session: SessionState, to_state: StateType) -> None: ...
```

**验收标准:**
- 原 `conversation_orchestrator.py` 被删除或保留为薄代理
- 每个新文件 < 200 行
- 状态转移有明确定义，非法转移抛异常
- 集成测试验证原有功能不回退

---

#### Task R-4: Agent 层依赖注入改造

**目标:** Agent 不再自行创建 Storage/Service 实例，全部通过构造函数接收

**当前问题:**
```python
# src/agents/interview_agent.py:54-56 (违规)
from src.storage.markdown_file_manager import MarkdownFileManager
from src.storage.memory_repository import MemoryRepository
self.memory_manager = MemoryManager(repository=MemoryRepository(file_manager=MarkdownFileManager()))
```

**重构方案:**
- `InterviewSessionAgent` 作为 Composition Root：创建所有共享依赖
- `InterviewAgent` 和 `ProfileCollectionAgent` 通过构造函数接收依赖
- Agent 的 `__init__` 中所有核心依赖为必需参数

**验收标准:**
- Agent 文件中无 `from src.storage.*` 导入
- Agent 文件中无 `MarkdownFileManager()` 或 `MemoryRepository()` 实例化
- 所有依赖创建集中在一处（InterviewSessionAgent 或工厂）

---

### Phase 2: 代码质量提升 (MAJOR) — 2~3 天

#### Task R-5: 定义接口抽象层

**目标:** 为核心服务定义 Protocol/ABC 接口，支持实现替换

**新增文件:** `src/interfaces/`

```python
# src/interfaces/__init__.py
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class ILLMProvider(ABC):
    @abstractmethod
    async def invoke(self, prompt: str, **kwargs) -> Any: ...
    @abstractmethod
    async def invoke_structured(self, template: str, variables: Dict, output_model: type) -> tuple: ...

class IMemoryStore(ABC):
    @abstractmethod
    async def save_event(self, user_id: str, event: 'EventInfo') -> str: ...
    @abstractmethod
    async def load_events(self, user_id: str, **criteria) -> List['EventInfo']: ...
    @abstractmethod
    def get_short_term(self, key: str) -> Optional[Any]: ...
    @abstractmethod
    def update_short_term(self, key: str, value: Any) -> None: ...

class IFileStorage(ABC):
    @abstractmethod
    async def read_file(self, path: str) -> str: ...
    @abstractmethod
    async def write_file(self, path: str, content: str) -> None: ...
    @abstractmethod
    async def search_files(self, directory: str, pattern: str) -> List[str]: ...
```

**验收标准:**
- 所有核心服务实现对应接口
- 类型注解使用接口而非具体类
- 可用 mock 实现通过测试验证

---

#### Task R-6: 整合 Memory 管理职责

**目标:** 消除 4 个类之间的职责重叠

**当前状态:**
- `MemoryRepository`: 三层存储 + LRU + 事件索引 + **查询委派**(违规)
- `MemoryManager`: 高层编排 + LLM 组织 + 抽取
- `MemoryCacheTool`: 会话级缓存
- `MemoryArchiveTool`: 归档操作

**重构后职责:**
- `MemoryRepository`（纯存储层）: 短期内存字典、长期文件 CRUD、Profile JSON CRUD、LRU 缓存管理
- `MemoryManager`（服务层）: LLM 组织/抽取、事件归档协调、查询协调、MemoryCacheTool/MemoryArchiveTool 的功能合并至此
- 删除 `MemoryCacheTool` 和 `MemoryArchiveTool` 作为独立类（合入 MemoryManager）

**验收标准:**
- `MemoryRepository` 无 LLM 相关代码
- `MemoryCacheTool` 和 `MemoryArchiveTool` 被移除或降级为 MemoryManager 的内部方法
- 功能完整，无遗漏

---

#### Task R-7: 丰富领域模型

**目标:** 将散落的业务逻辑归入模型，消除贫血模型

**示例改造 — SessionState:**
```python
class SessionState(BaseModel):
    # 新增行为方法
    def calculate_phase_progress(self) -> float:
        """计算当前阶段完成度"""

    def should_transition_phase(self) -> bool:
        """基于覆盖率判断是否应切换阶段"""

    def get_context_for_generation(self) -> Dict:
        """为问题生成准备上下文"""

    def get_recent_history(self, n: int = 5) -> List[ConversationTurn]:
        """获取最近 n 轮对话"""
```

**规则:**
- 仅与自身数据强相关的逻辑放入 Model
- 涉及外部 I/O、LLM 调用的逻辑留在 Service
- 验证逻辑使用 Pydantic validator

---

#### Task R-8: 文件 I/O 全面 async 化

**目标:** `MarkdownFileManager` 所有文件操作使用 `aiofiles`

**当前问题:**
```python
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()  # 阻塞事件循环
```

**重构方案:**
- 引入 `aiofiles` 依赖
- 所有 `open()` 替换为 `aiofiles.open()`
- 方法签名全部改为 `async def`
- 调用链路相应调整

---

### Phase 3: 性能优化 — 1~2 天

#### Task R-9: 文件查询缓存

**目标:** 避免同一轮对话中重复读取相同文件

**方案:** 新增 `src/storage/file_cache.py`
```python
class FileCache:
    def __init__(self, ttl_seconds: float = 30):
        self._cache: Dict[str, Tuple[str, float]] = {}

    async def read_cached(self, path: str) -> str:
        """带 TTL 的缓存读取"""

    def invalidate(self, path: str = None) -> None:
        """手动失效（写入后调用）"""
```

---

#### Task R-10: Token 预算与限流

**目标:** 实现 Spec 要求的"成本控制：统一的 Token 计数和成本统计"

**方案:** 新增 `src/services/token_budget.py`
```python
class TokenBudget:
    def __init__(self, max_tokens_per_session: int = 50000):
        self.max_tokens = max_tokens_per_session
        self.used_tokens = 0

    def try_allocate(self, estimated_tokens: int) -> bool: ...
    def record_usage(self, actual_tokens: int) -> None: ...
    def remaining(self) -> int: ...
```

---

#### Task R-11: Prompt 集中管理

**目标:** 单一 Prompt 注册中心，消除散落问题

**当前问题:**
- `src/prompts/` 目录含 markdown 和 Python 文件
- 根目录 `Prompts/` 目录也有 markdown prompt
- LLMService 在初始化时遍历目录加载

**方案:**
- 新增 `src/prompts/registry.py` 作为唯一 Prompt 入口
- 所有 Prompt 模板注册在此，支持懒加载
- 删除根目录 `Prompts/` 或将其标记为 deprecated
- LLMService 通过 `PromptRegistry.get(name)` 获取，不再自行遍历

---

### Phase 4: 规范化收尾 — 1 天

#### Task R-12: 工厂模式标准化

**新增:** `src/factories/`
```python
# src/factories/service_factory.py
class ServiceFactory:
    @staticmethod
    def create_memory_manager(user_id: str, llm_service: ILLMProvider) -> MemoryManager: ...

    @staticmethod
    def create_interview_orchestrator(llm_service: ILLMProvider, memory_manager: MemoryManager) -> InterviewOrchestrator: ...
```

---

#### Task R-13: 常量提取

**新增:** `src/config/constants.py`
```python
class SessionConfig:
    TOTAL_DURATION_MINUTES = 15
    PROFILE_DURATION_MINUTES = 5
    INTERVIEW_DURATION_MINUTES = 10
    TIME_WARNING_THRESHOLD = 0.8

class MemoryConfig:
    SHORT_TERM_CAPACITY = 20
    LONG_TERM_CACHE_SIZE = 100
    KB_SEARCH_MAX_RESULTS = 10

class LLMConfig:
    DEFAULT_TEMPERATURE = 0.7
    MAX_RETRIES = 3
    TIMEOUT_SECONDS = 30
```

---

#### Task R-14: 统一错误处理模式

**目标:** 所有 Service 返回一致的结果类型

```python
# src/models/result.py
from dataclasses import dataclass
from typing import Generic, TypeVar, Optional

T = TypeVar('T')

@dataclass
class Result(Generic[T]):
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    @classmethod
    def ok(cls, data: T) -> 'Result[T]':
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: str, code: str = None) -> 'Result[T]':
        return cls(success=False, error=error, error_code=code)
```

**规则:**
- 所有 Service 的公开方法返回 `Result[T]`
- 调用方决定：降级/传播/日志
- 不再混用 `None` / 空结构 / 异常

---

## 4. 约束与原则

1. **依赖方向单向:** Models ← Storage ← Services ← Agents（严禁反向）
2. **显式优于隐式:** 所有依赖通过构造函数注入，禁止隐式全局访问
3. **单一职责:** 每个类 < 200 行，超出则拆分
4. **接口隔离:** 消费方依赖接口（Protocol/ABC），不依赖具体类
5. **DRY:** 相同模式出现 3 次以上必须提取
6. **Async 优先:** 所有 I/O 操作必须 async
7. **集中创建:** 对象创建集中在 Composition Root 或 Factory

---

## 5. 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 循环依赖拆解引入回归 | Medium | 先写集成测试覆盖核心路径再重构 |
| Orchestrator 拆分遗漏逻辑 | Medium | 逐个方法搬迁，每搬一个跑一次测试 |
| async 化后调用链断裂 | Low | IDE 类型检查 + 全量 pytest 验证 |
| 接口设计过度抽象 | Low | 仅为需替换的组件定义接口，其余用具体类 |

---

## 6. 执行顺序依赖图

```
R-1 (消除循环依赖)
 └─► R-2 (消除全局状态)
      └─► R-4 (Agent 依赖注入)
           └─► R-6 (整合 Memory 管理)

R-3 (拆分 Orchestrator)     [可与 R-1/R-2 并行]
 └─► R-5 (接口抽象)

R-7 (丰富模型)              [可与 Phase 1 并行]
R-8 (async 化)              [依赖 R-1 完成]

R-9 ~ R-14 (Phase 3+4)     [依赖 Phase 1+2 完成]
```
