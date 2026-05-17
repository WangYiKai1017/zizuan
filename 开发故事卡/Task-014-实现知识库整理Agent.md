# 开发故事卡 - Task 014: 实现知识库整理 Agent

> 任务编号：Task-014
> 优先级：P0
> 依赖：无（独立功能模块，复用现有基础设施）
> 预计工时：4-5 天

---

## 一、任务概述

### 1.1 核心职责

知识库整理 Agent（`KBOrganizerAgent`）负责对老人采访知识库进行自动化归纳整理，为自传编写做准备。核心能力：

- **重复检测与合并**：识别语义重复或高度相似的事件/人物文档，合并为单一文档，严禁丢失任何细节
- **矛盾识别与修复**：发现文档间的事实矛盾（时间、地点、人物关系等），在已有信息中尝试解决，无法解决的记录为待澄清问题
- **链接完整性维护**：合并文档后修复所有 Wiki 链接引用，确保无断链
- **对话记录清理**：仅保留最新两份对话记录，删除历史归档
- **安全工作流**：在临时副本上操作，完成后原子替换原目录

### 1.2 架构定位

```
┌─────────────────────────────────────────────────────────────┐
│                    KBOrganizerAgent                         │
│              (Plan-Execute / ReAct Loop)                    │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Planner     │  │  Executor    │  │  StateTracker    │  │
│  │  (LLM-based) │  │  (Tool Call) │  │  (Task Board)    │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │            │
│         ▼                 ▼                    ▼            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │               KBOrganizationService                  │   │
│  │  (核心业务逻辑：合并 / 矛盾检测 / 链接修复)          │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
│  ┌──────────┬───────────┼───────────┬──────────────────┐   │
│  ▼          ▼           ▼           ▼                  ▼   │
│ LLMService  Markdown   EventInfo  PersonInfo  PromptTemplate│
│ (复用)      FileManager (复用)     (复用)      (复用)       │
│             (复用)                                          │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 Agent 运行模式

采用 **Plan-Execute（基于 ReAct）** 模式：

```
                    ┌─────────────┐
                    │   START     │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  Plan Phase │◄──────────────┐
                    │  (生成/更新  │               │
                    │   任务计划)  │               │
                    └──────┬──────┘               │
                           ▼                      │
                    ┌─────────────┐               │
                    │ Execute     │               │
                    │ (执行当前   │               │
                    │  最优先任务) │               │
                    └──────┬──────┘               │
                           ▼                      │
                    ┌─────────────┐               │
                    │ Observe     │               │
                    │ (评估结果,  │───── 未完成 ──┘
                    │  更新状态)  │
                    └──────┬──────┘
                           │ 全部完成
                           ▼
                    ┌─────────────┐
                    │    END      │
                    └─────────────┘
```

---

## 二、核心对象定义

### 2.1 Agent 状态定义

```python
# src/models/kb_organizer_state.py

from enum import Enum
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class TaskStatus(str, Enum):
    """整理任务状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class OrganizerTask(BaseModel):
    """单个整理任务"""
    task_id: str
    task_type: str                           # setup_workspace / merge_duplicates / resolve_conflicts / ...
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None             # 执行结果摘要
    error: Optional[str] = None              # 错误信息
    affected_files: List[str] = Field(default_factory=list)


class ConflictItem(BaseModel):
    """矛盾问题记录"""
    conflict_id: str
    description: str                          # 矛盾描述（标准化格式）
    source_files: List[str]                   # 涉及的文档路径
    resolved: bool = False
    resolution: Optional[str] = None          # 解决方案描述
    evidence: Optional[str] = None            # 支撑解决的证据来源


class MergeRecord(BaseModel):
    """合并记录"""
    merge_id: str
    source_files: List[str]                   # 被合并的源文件列表
    target_file: str                          # 合并后的目标文件
    merge_reason: str                         # 合并原因
    preserved_details: List[str]              # 保留的关键细节清单


class KBOrganizerState(BaseModel):
    """知识库整理 Agent 全局状态"""
    user_id: str
    source_path: str                          # 原始知识库路径 {folder_name}
    working_path: str                         # 工作副本路径 {folder_name}_temp
    
    # 任务板
    task_plan: List[OrganizerTask] = Field(default_factory=list)
    current_task_index: int = 0
    
    # 文档清单
    all_files: Dict[str, List[str]] = Field(default_factory=dict)  # category -> [file_paths]
    
    # 合并记录
    merge_records: List[MergeRecord] = Field(default_factory=list)
    
    # 矛盾管理
    conflict_items: List[ConflictItem] = Field(default_factory=list)
    
    # 链接映射（旧路径 -> 新路径）
    link_redirect_map: Dict[str, str] = Field(default_factory=dict)
    
    # 运行元数据
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    iteration_count: int = 0

    def get_current_task(self) -> Optional[OrganizerTask]:
        """获取当前待执行任务"""
        pending = [t for t in self.task_plan if t.status == TaskStatus.PENDING]
        return pending[0] if pending else None

    def all_tasks_done(self) -> bool:
        """检查是否所有任务已完成"""
        return all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
            for t in self.task_plan
        )

    def get_active_conflicts(self) -> List[ConflictItem]:
        """获取未解决的矛盾列表"""
        return [c for c in self.conflict_items if not c.resolved]

    def register_merge(self, sources: List[str], target: str, reason: str, details: List[str]) -> None:
        """注册一次合并操作，同时更新链接映射"""
        record = MergeRecord(
            merge_id=f"merge_{len(self.merge_records) + 1:03d}",
            source_files=sources,
            target_file=target,
            merge_reason=reason,
            preserved_details=details,
        )
        self.merge_records.append(record)
        for src in sources:
            if src != target:
                self.link_redirect_map[src] = target
```

### 2.2 核心业务服务

```python
# src/services/kb_organization_service.py

class KBOrganizationService:
    """知识库整理核心业务逻辑
    
    职责：
    - 文档相似度分析与合并决策
    - 矛盾检测与修复
    - 链接完整性校验与修复
    - conflict.md 管理
    
    依赖注入：
    - llm_service: LLMService (必需)
    - file_manager: MarkdownFileManager (必需)
    """
    
    def __init__(
        self,
        llm_service: LLMService,
        file_manager: MarkdownFileManager,
    ):
        self.llm_service = llm_service
        self.file_manager = file_manager

    # ── 重复检测与合并 ──────────────────────────────────────

    async def find_duplicate_groups(
        self, file_paths: List[str]
    ) -> List[List[str]]:
        """识别语义重复/高度相似的文档组
        
        使用 LLM 对文档摘要进行语义聚类，返回应合并的文件分组。
        每组内的文件描述的是同一事件或可合并的相似事件。
        
        Returns:
            分组列表，每组包含 >= 2 个应合并的文件路径
        """
        ...

    async def merge_documents(
        self, file_paths: List[str], category: str
    ) -> MergeRecord:
        """将多个文档合并为一个，严禁丢失任何细节
        
        合并规则：
        1. 保留所有细节描述，不得擅自删减
        2. 合并相同字段时取并集（如 participants、emotions）
        3. 冲突字段标注来源
        4. 使用信息最完整的文件名作为目标文件名
        5. 更新 来源记录 字段，追溯所有原始 session/turn
        
        Args:
            file_paths: 待合并文件路径列表
            category: 文件类别 (events/people)
        
        Returns:
            MergeRecord 记录合并详情
        """
        ...

    # ── 矛盾检测与修复 ──────────────────────────────────────

    async def detect_contradictions(
        self, file_paths: List[str]
    ) -> List[ConflictItem]:
        """扫描文档集合，识别事实矛盾
        
        检测维度：
        - 时间矛盾（同一事件不同时间记录）
        - 地点矛盾（同一事件不同地点）
        - 人物关系矛盾（同一人物不同关系描述）
        - 因果矛盾（事件顺序逻辑不通）
        
        Returns:
            矛盾问题列表
        """
        ...

    async def try_resolve_conflict(
        self, conflict: ConflictItem, all_documents: Dict[str, str]
    ) -> ConflictItem:
        """尝试在已有文档信息中解决矛盾
        
        使用 LLM 分析矛盾涉及的文档上下文，判断是否有足够证据
        确定正确信息。如果能解决，更新文档内容并标记已解决。
        
        Args:
            conflict: 待解决的矛盾
            all_documents: 所有相关文档内容 {path: content}
        
        Returns:
            更新后的 ConflictItem（resolved=True 或保持 False）
        """
        ...

    # ── conflict.md 管理 ────────────────────────────────────

    async def load_conflict_file(self, path: str) -> List[ConflictItem]:
        """解析 conflict.md 中的问题列表"""
        ...

    async def save_conflict_file(
        self, path: str, conflicts: List[ConflictItem]
    ) -> None:
        """将矛盾问题列表写入 conflict.md（标准格式）"""
        ...

    # ── 链接校验与修复 ──────────────────────────────────────

    async def validate_all_links(
        self, working_path: str
    ) -> List[Dict[str, str]]:
        """校验工作目录下所有 markdown 文件中的链接
        
        Returns:
            断链列表 [{file, link, reason}]
        """
        ...

    async def repair_links(
        self, working_path: str,
        redirect_map: Dict[str, str]
    ) -> int:
        """根据重定向映射修复所有文档中的链接
        
        Returns:
            修复的链接数量
        """
        ...

    # ── 对话记录清理 ────────────────────────────────────────

    async def prune_conversations(
        self, working_path: str, keep_latest: int = 2
    ) -> List[str]:
        """仅保留最新 N 份对话记录，删除其余
        
        对话文件命名格式：conversation_YYYY-MM-DD_HH-MM-SS.json
        按时间戳排序，保留最新的 keep_latest 份。
        同样处理 logs/ 目录下的 .log 文件。
        
        Returns:
            被删除的文件路径列表
        """
        ...
```

### 2.3 Agent 主体

```python
# src/agents/kb_organizer_agent.py

class KBOrganizerAgent:
    """知识库整理 Agent
    
    采用 Plan-Execute (ReAct) 模式运行：
    1. Plan: 基于当前状态生成/更新任务计划
    2. Execute: 调用 KBOrganizationService 执行当前任务
    3. Observe: 评估结果，决定继续或终止
    
    依赖注入（全部必需，无隐式全局状态）：
    - llm_service: LLMService
    - organization_service: KBOrganizationService
    """
    
    def __init__(
        self,
        llm_service: LLMService,
        organization_service: KBOrganizationService,
    ):
        self.llm_service = llm_service
        self.organization_service = organization_service
        self.state: Optional[KBOrganizerState] = None

    async def run(self, target_path: str) -> KBOrganizerState:
        """执行完整的知识库整理流程
        
        Args:
            target_path: 目标知识库文件夹路径
            
        Returns:
            最终状态（含所有合并记录、矛盾记录、执行结果）
        """
        self.state = await self._initialize_state(target_path)
        
        while not self.state.all_tasks_done():
            self.state.iteration_count += 1
            
            # Plan: 获取下一个任务
            current_task = self.state.get_current_task()
            if current_task is None:
                break
            
            # Execute: 执行任务
            current_task.status = TaskStatus.IN_PROGRESS
            await self._execute_task(current_task)
            
            # Observe: 评估是否需要调整计划
            await self._observe_and_replan()
        
        # 最终收尾
        await self._finalize()
        return self.state

    async def _initialize_state(self, target_path: str) -> KBOrganizerState:
        """初始化：创建工作副本，扫描文件清单，生成任务计划"""
        ...

    async def _execute_task(self, task: OrganizerTask) -> None:
        """根据任务类型路由到对应的执行方法"""
        ...

    async def _observe_and_replan(self) -> None:
        """评估当前执行结果，必要时调整后续任务计划"""
        ...

    async def _finalize(self) -> None:
        """原子替换：{folder_name} -> {folder_name}_{timestamp}，
        {folder_name}_temp -> {folder_name}"""
        ...
```

### 2.4 LangGraph 图定义

```python
# src/agents/kb_organizer_graph.py

from langgraph.graph import StateGraph, END
from src.models.kb_organizer_state import KBOrganizerState

def build_kb_organizer_graph(agent: KBOrganizerAgent) -> StateGraph:
    """构建知识库整理 Agent 的 LangGraph 执行图
    
    节点：
    - plan: 生成/更新任务计划
    - execute: 执行当前任务
    - observe: 评估结果并决定下一步
    
    边：
    - plan -> execute
    - execute -> observe
    - observe -> plan (如果还有未完成任务)
    - observe -> END (如果所有任务完成)
    """

    graph = StateGraph(KBOrganizerState)

    # 注册节点
    graph.add_node("plan", agent.plan_node)
    graph.add_node("execute", agent.execute_node)
    graph.add_node("observe", agent.observe_node)

    # 定义边
    graph.set_entry_point("plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "observe")
    graph.add_conditional_edges(
        "observe",
        agent.should_continue,
        {
            "continue": "plan",
            "end": END,
        }
    )

    return graph.compile()
```

---

## 三、任务执行流程（Task Pipeline）

Agent 的任务计划按以下固定顺序生成，每个任务对应一个原子操作：

### Step 1: 创建工作空间 (`setup_workspace`)

```
输入: target_path = "knowledge_base/test_user002"
操作:
  1. 创建 {folder_name}_temp 目录
  2. 递归复制 {folder_name}/ 下所有文件到 {folder_name}_temp/
  3. 扫描并记录所有文件清单到 state.all_files
  4. 后续规则：
     - 读操作 → 在 {folder_name} 执行
     - 写/编辑/删除 → 在 {folder_name}_temp 执行
输出: state.working_path 已设置, state.all_files 已填充
```

### Step 2: 阅读文档 (`read_documents`)

```
操作:
  1. 遍历读取 {folder_name} 下所有 .md 文件
  2. 按类别分组：events/{phase}/, people/{role}/, timeline/, themes/
  3. 构建文档内容索引（内存中）
输出: 全部文档内容已加载到内存
```

### Step 3: 重复检测与合并 (`merge_duplicates`)

```
操作:
  1. 对 events/ 下每个子目录的文件调用 find_duplicate_groups()
  2. 对 people/ 下每个子目录的文件调用 find_duplicate_groups()
  3. 对每组重复文件调用 merge_documents()
  4. 在 {folder_name}_temp 中执行合并（创建合并文件、删除冗余文件）
  5. 记录所有 MergeRecord 和 link_redirect_map

合并原则：
  - 严禁擅自移除任何细节描述
  - 目标：减少文件数量、移除不必要的冗余
  - 合并后文件包含所有源文件的全部信息
  - 保留最具描述性的文件名

输出: state.merge_records 更新, state.link_redirect_map 更新
```

### Step 4: 检查 conflict.md (`check_conflicts`)

```
操作:
  1. 在 {folder_name}_temp 中检查是否存在 conflict.md
  2. 如果存在：
     a. 解析问题列表
     b. 逐条检查问题，判断当前文档中是否有答案能回答此矛盾
     c. 如果有证据可解决 → 修复文档中的冲突内容，移除此问题
     d. 如果无法解决 → 保留此问题
  3. 如果不存在：跳过此步骤

输出: state.conflict_items 更新（来自已有 conflict.md）
```

### Step 5: 矛盾检测 (`detect_contradictions`)

```
操作:
  1. 对当前所有文档执行矛盾检测 detect_contradictions()
  2. 新发现的矛盾尝试在已有信息中解决 try_resolve_conflict()
  3. 无法解决的矛盾添加到 state.conflict_items
  4. 将最终矛盾列表写入 {folder_name}_temp/conflict.md

矛盾记录格式（标准化）：
  每条矛盾必须包含：
  - 矛盾编号
  - 矛盾类型（时间 / 地点 / 人物关系 / 事件逻辑）
  - 矛盾描述（用通俗语言说清楚矛盾点，让读者一看即懂）
  - 涉及文档（列出相关文件路径）
  - 具体矛盾内容（引用文档中的原文）

输出: conflict.md 已更新
```

### Step 6: 链接修复 (`repair_links`)

```
操作:
  1. 调用 validate_all_links() 扫描所有断链
  2. 基于 state.link_redirect_map 调用 repair_links() 修复
  3. 对 timeline/life-events.md 和 index.md 进行特别检查
  4. 重新验证确保零断链

输出: 所有链接已修复并验证
```

### Step 7: 清理对话记录 (`prune_conversations`)

```
操作:
  1. 列出 {folder_name}_temp/ 下所有 conversation_*.json 文件
  2. 列出 {folder_name}_temp/logs/ 下所有 conversation_*.log 文件
  3. 按时间戳排序，仅保留最新 2 份
  4. 删除其余对话文件

输出: 仅保留 2 份最新对话
```

### Step 8: 原子替换 (`finalize_swap`)

```
操作:
  1. 将 {folder_name} 重命名为 {folder_name}_{YYYYMMDD_HHMMSS}
  2. 将 {folder_name}_temp 重命名为 {folder_name}
  3. 验证新目录结构完整性

输出: 知识库整理完成，原始数据已备份
```

---

## 四、Prompt 文件规范

所有 Prompt 以独立 `.md` 文件存放于 `src/prompts/` 目录，禁止将提示词嵌入代码。

### 4.1 需创建的 Prompt 文件

| 文件名 | 用途 | 关键变量 |
|--------|------|----------|
| `KBDuplicateDetector-Prompt.md` | 检测文档语义重复/相似性 | `${documents_summary}`, `${category}` |
| `KBDocumentMerger-Prompt.md` | 合并多份文档为一份 | `${source_documents}`, `${merge_rules}` |
| `KBConflictDetector-Prompt.md` | 扫描文档中的事实矛盾 | `${documents_content}`, `${known_facts}` |
| `KBConflictResolver-Prompt.md` | 尝试在已有信息中解决矛盾 | `${conflict_description}`, `${evidence_documents}` |

### 4.2 Prompt 文件格式（遵循项目现有规范）

```markdown
# [功能名称] 动态 Prompt 模板

> 模板名称：`template_key`
> 职责：一句话描述
> 版本：v1.0
> 日期：YYYY-MM-DD

## Prompt 模板结构
1. 系统角色
2. 任务说明
3. 输入信息
4. 处理原则
5. 输出格式

## 系统角色
...

## 任务说明
...使用 ${variable_name} 作为占位符...

## 输入信息
...

## 处理原则
...

## 输出格式
...（JSON / Markdown 结构定义）...

## 示例
...
```

### 4.3 各 Prompt 核心指导原则

**KBDuplicateDetector-Prompt.md:**
- 判断依据：事件主体相同、核心参与者重叠、时间地点相近
- 区分"重复"与"相关但不同"事件
- 输出：分组 JSON，每组包含应合并的文件列表及判断理由

**KBDocumentMerger-Prompt.md:**
- **绝对原则：严禁删除任何细节描述**
- 合并策略：取信息并集，冲突字段标注来源
- 输出：合并后的完整 Markdown 文档内容

**KBConflictDetector-Prompt.md:**
- 检测维度：时间、地点、人物关系、事件逻辑因果
- 输出：矛盾清单 JSON，每条含类型、描述、涉及文档、原文引用
- 矛盾描述需通俗易懂，让非技术人员也能理解矛盾点

**KBConflictResolver-Prompt.md:**
- 只基于已有文档信息推理，不虚构事实
- 输出：是否可解决、解决方案、修改内容、证据来源

---

## 五、复用现有对象清单

### 5.1 直接复用（无需修改）

| 对象 | 路径 | 复用方式 |
|------|------|----------|
| `LLMService` | `src/services/llm_service.py` | 所有 LLM 调用 |
| `LLMConfig` | `src/config/llm_config.py` | 配置加载 |
| `MarkdownFileManager` | `src/storage/markdown_file_manager.py` | 文件读写、搜索、链接提取 |
| `PromptTemplate` | `src/prompts/base.py` | Prompt 模板管理 |
| `EventInfo` | `src/models/event_info.py` | 事件数据模型 |
| `PersonInfo` | `src/models/person_info.py` | 人物数据模型 |

### 5.2 新建对象

| 对象 | 路径 | 职责 |
|------|------|------|
| `KBOrganizerState` | `src/models/kb_organizer_state.py` | Agent 全局状态 |
| `OrganizerTask` | `src/models/kb_organizer_state.py` | 单个任务定义 |
| `ConflictItem` | `src/models/kb_organizer_state.py` | 矛盾问题记录 |
| `MergeRecord` | `src/models/kb_organizer_state.py` | 合并操作记录 |
| `KBOrganizationService` | `src/services/kb_organization_service.py` | 核心业务逻辑 |
| `KBOrganizerAgent` | `src/agents/kb_organizer_agent.py` | Agent 主体 |
| `build_kb_organizer_graph` | `src/agents/kb_organizer_graph.py` | LangGraph 图定义 |

---

## 六、OOP 设计约束

### 6.1 强制规则

1. **依赖注入**：所有依赖通过构造函数注入，禁止 `get_llm_service()` 等隐式全局访问
2. **单一职责**：每个类 ≤ 250 行；超出则拆分
3. **层级方向**：Models ← Services ← Agents，禁止反向引用
4. **无 Prompt 嵌入**：所有提示词存放在独立 `.md` 文件中，通过 `LLMService.invoke_with_template()` 调用
5. **类型标注**：所有公开方法必须有完整的类型注解和 docstring
6. **错误处理**：使用统一的错误处理模式，不混用 None / 异常 / 空结构

### 6.2 数据流向

```
KBOrganizerAgent
  │
  ├── 持有 KBOrganizerState (状态)
  ├── 持有 KBOrganizationService (业务逻辑)
  │     ├── 持有 LLMService (LLM 调用)
  │     └── 持有 MarkdownFileManager (文件操作)
  └── 通过 LangGraph 编排执行流
```

### 6.3 文件操作安全规则

```
读操作源路径:   state.source_path     ({folder_name})
写操作目标路径: state.working_path    ({folder_name}_temp)

所有文件修改必须通过 MarkdownFileManager 执行，禁止直接 os/shutil 操作
仅在最终 finalize_swap 阶段执行目录重命名（此为唯一允许的 os 级操作）
```

---

## 七、conflict.md 标准格式

```markdown
# 待核实问题清单

> 最后更新：YYYY-MM-DD HH:MM
> 未解决问题数：N

---

## 问题 001

- **矛盾类型**：时间矛盾
- **矛盾描述**：寇治协的出生年份在不同文档中记录不一致。一处记载为1931年，另一处记载为1930年。
- **涉及文档**：
  - `events/elderly/出生.md`
  - `events/elderly/寇治协出生.md`
- **具体内容**：
  > 出生.md 中记载："1931年出生于河北"
  > 寇治协出生.md 中记载："约1930年出生"
- **状态**：待核实

---

## 问题 002
...
```

---

## 八、验收标准

### 8.1 功能验收

- [ ] 对 test_user002 知识库执行完整整理流程，无报错
- [ ] 重复事件文件被正确合并（如 `参军.md` 与 `参军成为通信兵.md`）
- [ ] 合并后文档包含所有源文件的全部细节，无信息丢失
- [ ] 所有 Wiki 链接指向有效文件
- [ ] 仅保留最新 2 份对话记录
- [ ] 原始知识库备份为 `{folder_name}_{timestamp}`
- [ ] 整理后知识库取代原目录
- [ ] conflict.md 格式标准，矛盾描述清晰可读

### 8.2 代码质量验收

- [ ] 所有 Prompt 存放在 `src/prompts/` 下独立 `.md` 文件中
- [ ] 代码中无硬编码的提示词字符串
- [ ] 所有类通过构造函数注入依赖，无隐式全局状态
- [ ] 每个类 ≤ 250 行
- [ ] 所有公开方法有类型注解和 docstring
- [ ] `mypy --strict` 无报错
- [ ] `black` + `isort` 格式化通过
- [ ] 无循环依赖（可通过 `import` 静态分析验证）

### 8.3 测试验收

- [ ] 为 `KBOrganizationService` 核心方法编写单元测试
- [ ] 为 `KBOrganizerAgent.run()` 编写端到端集成测试
- [ ] 使用 test_user001 知识库作为第二套测试数据验证通用性

---

## 九、参考资源

| 资源 | 路径 | 用途 |
|------|------|------|
| 测试知识库 | `knowledge_base/test_user002/` | 主要测试数据 |
| 备选测试数据 | `knowledge_base/test_user001/` | 通用性验证 |
| 文件管理器 | `src/storage/markdown_file_manager.py` | 文件操作复用 |
| LLM 服务 | `src/services/llm_service.py` | LLM 调用复用 |
| Prompt 基类 | `src/prompts/base.py` | Prompt 模板复用 |
| 事件模型 | `src/models/event_info.py` | 数据模型复用 |
| 现有 Prompt 范例 | `src/prompts/ContentSummarizer-Prompt.md` | Prompt 格式参考 |
| 重构 Spec | `开发故事卡/Refactor-底层代码优化重构Spec.md` | 架构约束参考 |
