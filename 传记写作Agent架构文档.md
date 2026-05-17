# 传记写作 Agent 架构文档

## 一、系统概览

### 1.1 双 Agent 架构

传记写作系统采用 **双 Agent 流水线架构**，将传记生成过程分为两个独立又协作的阶段：

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **BiographyOutlineAgent** | 分析知识库素材，生成/更新章节大纲 | 知识库（events/people/timeline） | `outline.yaml` |
| **BiographyWritingAgent** | 将已确认的章节大纲转化为散文 | `outline.yaml` + 知识库素材 | 章节 `.md` + `full_biography.md` |

### 1.2 工作流概述

```
┌─────────────────────────────────────────────────────────────────────┐
│                        完整工作流                                    │
│                                                                     │
│  ┌──────────┐   ┌─────────────────┐   ┌──────────┐   ┌──────────┐  │
│  │ 知识库    │──▶│ OutlineAgent    │──▶│ 用户确认  │──▶│ Writing  │  │
│  │ (KB)     │   │ 扫描→分析→规划  │   │ draft →  │   │ Agent    │  │
│  │ events/  │   │                 │   │ confirmed│   │ 逐章写作  │  │
│  │ people/  │   │                 │   │          │   │          │  │
│  │ timeline/│   │                 │   │          │   │          │  │
│  └──────────┘   └────────┬────────┘   └──────────┘   └────┬─────┘  │
│                          │                                 │        │
│                          ▼                                 ▼        │
│                   outline.yaml                      chapters/*.md   │
│                   .state.json                    full_biography.md  │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 核心设计决策

- **文件系统作为共享状态**：两个 Agent 通过 `outline.yaml` 文件进行状态传递，无需进程间通信
- **增量处理机制**：通过 `.state.json` 中的内容哈希值检测知识库变更，避免重复处理
- **用户确认环节**：大纲生成后需人工将章节状态从 `draft` 改为 `confirmed`，确保用户对内容的控制权
- **自我审阅循环**：WritingAgent 内置 LLM 审阅机制，对生成的初稿进行质量把关

### 1.4 技术栈

| 技术 | 用途 |
|------|------|
| **LangGraph StateGraph** | Agent 执行图定义与状态流转 |
| **Pydantic v2** | 数据模型定义与验证（`BaseModel`、`model_validate`、`model_dump`） |
| **async Python** | 所有 LLM 调用和 Agent 运行均为异步 |
| **LangChain / langchain-openai** | LLM 调用封装 |
| **PyYAML** | `outline.yaml` 的序列化/反序列化 |
| **hashlib (SHA256)** | 知识库内容变更检测 |

---

## 二、目录结构与文件说明

### 2.1 源码文件

```
src/
├── models/
│   ├── biography_models.py          # 共享数据模型（ChapterEntry、OutlineDocument 等）
│   ├── biography_outline_state.py   # OutlineAgent 的 LangGraph 状态
│   └── biography_writing_state.py   # WritingAgent 的 LangGraph 状态
├── agents/
│   ├── biography_outline_agent.py   # OutlineAgent 业务逻辑（图节点实现）
│   ├── biography_outline_graph.py   # OutlineAgent LangGraph 图定义
│   ├── biography_writing_agent.py   # WritingAgent 业务逻辑（图节点实现）
│   └── biography_writing_graph.py   # WritingAgent LangGraph 图定义
├── services/
│   ├── biography_file_manager.py    # 传记文件 I/O 管理
│   ├── biography_material_analyzer.py # 知识库材料扫描与解析
│   └── llm_service.py              # LLM 统一调用入口
└── prompts/
    ├── BiographyMaterialAnalyzer-Prompt.md  # 素材分析 Prompt
    ├── BiographyOutlinePlanner-Prompt.md    # 大纲规划 Prompt
    ├── BiographyChapterWriter-Prompt.md     # 章节写作 Prompt
    └── BiographyChapterReviewer-Prompt.md   # 章节审校 Prompt
```

### 2.2 输出目录结构

```
knowledge_base/<user_id>/biography/
├── outline.yaml          # 章节大纲（YAML 格式）
├── .state.json           # 增量处理状态（JSON 格式）
├── chapters/
│   ├── ch01_童年往事.md   # 各章节散文
│   ├── ch02_少年时光.md
│   └── ...
└── full_biography.md     # 合并后的完整传记
```

### 2.3 输出文件格式

**outline.yaml 结构示例：**

```yaml
title: 我的人生故事
author: test_user001
style: first_person_oral
version: 2
last_updated: '2026-05-13T22:51:01.123456'
chapters:
  - id: ch01
    title: 槐花飘香的童年
    life_stage: childhood
    theme: 家庭与亲情
    status: written
    source_materials:
      - events/childhood/奶奶做槐花饼.md
      - people/family/奶奶.md
    summary: 回忆童年时光，奶奶做的槐花饼承载了最温暖的记忆...
    confirmed_at: '2026-05-13T15:00:00'
    written_at: '2026-05-13T20:30:00'
  - id: ch02
    title: 风雨中的少年
    life_stage: youth
    theme: 个人成长与蜕变
    status: draft
    source_materials:
      - events/youth/第一次离家.md
    summary: 离开家乡的那个清晨，母亲站在村口...
    confirmed_at: null
    written_at: null
```

**.state.json 结构示例：**

```json
{
  "last_outline_run": "2026-05-13T22:51:01.123456",
  "kb_content_hash": "a1b2c3d4e5f6...",
  "processed_files": [
    "events/childhood/奶奶做槐花饼.md",
    "events/youth/第一次离家.md",
    "people/family/奶奶.md",
    "timeline/life-events.md"
  ],
  "chapter_versions": {
    "ch01": 2,
    "ch02": 2
  }
}
```

---

## 三、共享数据模型 (biography_models.py)

所有数据模型定义于 `src/models/biography_models.py`，被 OutlineAgent 和 WritingAgent 共用。

### 3.1 ChapterStatus 枚举

章节状态的完整生命周期：

```
                  用户确认                  写作完成
  ┌─────────┐  ────────────▶  ┌───────────┐  ──────────▶  ┌─────────┐
  │  DRAFT  │                 │ CONFIRMED │               │ WRITTEN │
  │ (新生成) │                 │ (待写作)   │               │ (已写作) │
  └─────────┘                 └───────────┘               └────┬────┘
       ▲                                                       │
       │                                                       │ 源材料变更
       │                    ┌──────────┐                       │
       └────────────────────│ OUTDATED │◀──────────────────────┘
             需重新规划      │ (已过时)  │
                            └──────────┘
```

```python
class ChapterStatus(str, Enum):
    DRAFT = "draft"          # 新生成，待用户确认
    CONFIRMED = "confirmed"  # 用户已确认，待写作
    WRITTEN = "written"      # 已完成写作
    OUTDATED = "outdated"    # 源材料变更，需更新
```

### 3.2 AgentStatus 枚举

```python
class AgentStatus(str, Enum):
    RUNNING = "running"      # 运行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败
```

### 3.3 LifeStage 枚举

```python
class LifeStage(str, Enum):
    CHILDHOOD = "childhood"      # 童年
    YOUTH = "youth"              # 青年
    MIDDLE_AGE = "middle_age"    # 中年
    ELDERLY = "elderly"          # 老年
```

### 3.4 核心数据模型详解

#### ChapterEntry — 章节条目

`outline.yaml` 中每一章的数据结构。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `id` | `str` | （必填） | 章节唯一标识，格式如 `ch01`、`ch02` |
| `title` | `str` | （必填） | 章节标题，具有文学性 |
| `life_stage` | `str` | （必填） | 所属人生阶段（childhood/youth/middle_age/elderly） |
| `theme` | `str` | （必填） | 章节主题，如"家庭与亲情" |
| `status` | `ChapterStatus` | `DRAFT` | 章节当前状态 |
| `source_materials` | `list[str]` | `[]` | 引用的知识库文件路径列表 |
| `summary` | `str` | `""` | 章节内容摘要（50-100字） |
| `confirmed_at` | `Optional[datetime]` | `None` | 用户确认时间戳 |
| `written_at` | `Optional[datetime]` | `None` | 写作完成时间戳 |

#### OutlineDocument — 大纲文档

`outline.yaml` 的完整顶层结构。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `title` | `str` | `"我的人生故事"` | 传记标题 |
| `author` | `str` | `""` | 传主姓名 |
| `style` | `str` | `"first_person_oral"` | 写作风格 |
| `version` | `int` | `1` | 大纲版本号，每次更新递增 |
| `last_updated` | `datetime` | `datetime.now()` | 最后更新时间 |
| `chapters` | `list[ChapterEntry]` | `[]` | 章节列表 |

#### EventSummary — 事件摘要

从知识库 `events/` 目录提取的事件结构化数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| `file_path` | `str` | 相对文件路径 |
| `title` | `str` | 事件标题 |
| `life_stage` | `str` | 人生阶段 |
| `event_type` | `str` | 事件类型 |
| `description` | `str` | 事件描述 |
| `people` | `list[str]` | 相关人物名称列表 |
| `emotion_tags` | `list[str]` | 情感标签列表 |

#### PersonSummary — 人物摘要

从知识库 `people/` 目录提取的人物结构化数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| `file_path` | `str` | 相对文件路径 |
| `name` | `str` | 人物姓名 |
| `relationship` | `str` | 与传主的关系 |
| `description` | `str` | 人物描述 |
| `influence` | `str` | 对传主的影响 |
| `quotes` | `list[str]` | 重要语录列表 |

#### TimelineEntry — 时间线条目

从知识库 `timeline/life-events.md` 提取的时间线数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| `life_stage` | `str` | 人生阶段 |
| `event_title` | `str` | 事件标题 |
| `event_type` | `str` | 事件类型 |
| `detail_link` | `str` | 详情链接 |

#### OutlineChange — 大纲变更记录

记录每次大纲更新的变更操作。

| 字段 | 类型 | 说明 |
|------|------|------|
| `action` | `str` | 操作类型：`add` / `update` / `mark_outdated` |
| `chapter_id` | `str` | 相关章节 ID |
| `chapter_entry` | `Optional[ChapterEntry]` | 新增章节的完整数据（仅 `add` 时） |
| `reason` | `str` | 变更原因 |

#### ChapterTask — 写作任务

WritingAgent 的任务队列项，从 `outline.yaml` 中筛选 `confirmed` 章节构建。

| 字段 | 类型 | 说明 |
|------|------|------|
| `chapter_id` | `str` | 章节 ID |
| `chapter_title` | `str` | 章节标题 |
| `life_stage` | `str` | 人生阶段 |
| `theme` | `str` | 章节主题 |
| `source_materials` | `list[str]` | 源材料路径 |
| `summary` | `str` | 章节摘要 |

#### BiographyState — 增量处理状态

`.state.json` 的数据结构，用于跨运行的增量检测。

| 字段 | 类型 | 说明 |
|------|------|------|
| `last_outline_run` | `Optional[datetime]` | 上次大纲生成的时间 |
| `kb_content_hash` | `str` | 知识库内容的 SHA256 哈希 |
| `processed_files` | `list[str]` | 已处理的文件列表 |
| `chapter_versions` | `dict[str, int]` | 各章节对应的大纲版本号 |

---

## 四、共享服务层

### 4.1 BiographyFileManager

**文件：** `src/services/biography_file_manager.py`

**职责：** 传记写作系统的所有文件 I/O 操作的统一管理器，包括大纲读写、状态管理、章节文件管理、知识库扫描和全文合并。

**构造函数：**

```python
class BiographyFileManager:
    def __init__(self, kb_path: str):
        """
        Args:
            kb_path: 知识库根路径，如 "knowledge_base/test_user001"
        """
        self.kb_path = kb_path
        self.biography_path = os.path.join(kb_path, "biography")
        self._ensure_directory_structure()  # 自动创建 biography/chapters/ 目录
```

**核心方法一览：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `load_outline` | `() -> Optional[OutlineDocument]` | 读取 `outline.yaml`，不存在返回 `None` |
| `save_outline` | `(outline: OutlineDocument) -> None` | 保存 `outline.yaml`，使用 `model_dump(mode="json")` 序列化 |
| `update_chapter_status` | `(chapter_id: str, status: ChapterStatus, timestamp_field: str = None) -> None` | 更新单个章节状态，可选设置时间戳字段 |
| `load_state` | `() -> BiographyState` | 读取 `.state.json`，不存在返回默认空状态 |
| `save_state` | `(state: BiographyState) -> None` | 保存 `.state.json` |
| `save_chapter` | `(chapter_id: str, title: str, content: str) -> str` | 保存章节 Markdown 文件，返回路径。自动处理同 ID 旧文件删除 |
| `load_chapter` | `(chapter_id: str) -> Optional[str]` | 按 chapter_id 前缀匹配读取章节文件 |
| `list_chapter_files` | `() -> list[str]` | 列出所有已写章节文件名 |
| `merge_chapters_to_full` | `(outline: OutlineDocument) -> str` | 按大纲顺序合并所有章节为 `full_biography.md` |
| `scan_kb_files` | `() -> list[str]` | 扫描知识库 events/people/timeline/themes 下所有 `.md` 文件 |
| `read_kb_file` | `(relative_path: str) -> str` | 读取单个知识库文件 |
| `read_kb_files_by_paths` | `(paths: list[str]) -> dict[str, str]` | 批量读取知识库文件，容错跳过 |
| `compute_kb_hash` | `() -> str` | 计算知识库全部文件内容的 SHA256 哈希值 |
| `detect_changes` | `(previous_state: BiographyState) -> list[str]` | 对比上次状态，检测新增文件 |

**关键实现细节：**

1. **YAML 安全序列化**：使用 `model_dump(mode="json")` 代替直接 dump 模型对象，确保 Enum 序列化为字符串、datetime 序列化为 ISO 格式，兼容 `yaml.safe_load()`。

2. **章节文件命名规则**：`{chapter_id}_{sanitized_title}.md`，例如 `ch01_槐花飘香的童年.md`。文件名中的特殊字符会被替换为下划线。

3. **全文合并格式**：`full_biography.md` 包含标题、作者、目录（带锚点链接）、分隔线、各章节内容。未完成章节显示占位文本。

4. **哈希计算逻辑**：对所有 KB 文件按路径排序后，依次 hash（路径 + 内容），生成单个 SHA256 值。任何文件的新增、删除或内容修改都会改变哈希。

### 4.2 BiographyMaterialAnalyzer

**文件：** `src/services/biography_material_analyzer.py`

**职责：** 纯粹的数据解析器，负责扫描和解析知识库中的采访材料，为 Agent 的 LLM 节点准备结构化输入。**不做任何 LLM 调用**，只做文件读取和 Markdown 内容解析。

**构造函数：**

```python
class BiographyMaterialAnalyzer:
    def __init__(self, file_manager: BiographyFileManager):
        self.file_manager = file_manager
```

**核心方法一览：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `scan_and_parse_all` | `() -> dict` | 扫描并解析所有材料，返回 `{events, people, timeline, raw_content}` |
| `parse_events` | `() -> list[EventSummary]` | 解析 `events/` 下所有事件文档 |
| `parse_people` | `() -> list[PersonSummary]` | 解析 `people/` 下所有人物文档 |
| `parse_timeline` | `() -> list[TimelineEntry]` | 解析 `timeline/life-events.md` 中的时间线 |
| `format_materials_for_llm` | `(events, people, timeline) -> str` | 将结构化数据格式化为 LLM 可读的分类文本 |
| `gather_chapter_materials` | `(source_materials: list[str], life_stage: str) -> dict` | 为特定章节收集写作素材 |

**事件解析逻辑 (`_parse_single_event`)：**

从每个事件 `.md` 文件中提取：
- **title**：从 `# 标题行`
- **life_stage**：从文件所在子目录名（`events/childhood/xxx.md` → `"childhood"`）
- **event_type**：从 `基本信息` section 的 `**事件类型**` 字段
- **description**：从 `事件描述` section
- **people**：从 `相关人物` section 中的 `[[path|显示名]]` wiki link
- **emotion_tags**：从 `情感标签` section 中的 `#标签` 格式

**人物解析逻辑 (`_parse_single_person`)：**

从每个人物 `.md` 文件中提取：
- **name**：从 `# 标题行`
- **relationship**：从 `基本信息` → `**关系**` 字段
- **description**：从 `基本信息` → `**描述**` 字段
- **influence**：从 `对主人公的影响` section
- **quotes**：从 `重要语录` section 中的 `>` 引用行

**时间线解析逻辑 (`parse_timeline`)：**

从 `timeline/life-events.md` 按 `## 标题` 分段，提取：
- **life_stage**：`## 标题` 内容
- **event_title**：`**事件**` 字段
- **event_type**：`**类型**` 字段
- **detail_link**：`**详情**` 字段

**`gather_chapter_materials` 的工作流程：**

```
1. 读取 source_materials 列表中所有文件的完整内容
2. 从源文件内容中提取 wiki link 引用的人物名
3. 根据人物名去 people/ 目录匹配对应的人物档案
4. 根据 life_stage 筛选对应的时间线条目
5. 返回 {source_content, character_profiles, timeline_context}
```

**LLM 格式化输出示例（`format_materials_for_llm` 产出）：**

```
=== 事件材料 ===

【童年时期】
1. 奶奶做槐花饼
   - 描述：每到春天槐花开的时候...
   - 相关人物：奶奶、爷爷
   - 情感：温馨、怀念

【青年时期】
1. 第一次离家
   - 描述：...

=== 人物档案 ===

1. 奶奶（祖母）
   - 描述：慈祥的老人...
   - 影响程度：深远
   - 语录："做人要踏实..."

=== 时间线 ===

【童年时期】
- 奶奶做槐花饼 (生活)
- ...
```

---

## 五、BiographyOutlineAgent 架构

### 5.1 State 模型 (OutlineAgentState)

**文件：** `src/models/biography_outline_state.py`

```python
class OutlineAgentState(BaseModel):
    """大纲规划 Agent 的 LangGraph 状态"""

    # ─── 配置 ───
    user_id: str                    # 用户标识
    kb_path: str                    # 知识库路径
    biography_path: str             # 传记输出目录路径

    # ─── 扫描阶段输出 ───
    events: list[EventSummary]      # 解析后的事件列表
    people: list[PersonSummary]     # 解析后的人物列表
    timeline: list[TimelineEntry]   # 解析后的时间线
    raw_materials_text: str         # 格式化后的材料文本（给 LLM 用）
    has_changes: bool               # 是否检测到知识库变更（默认 True）
    changed_files: list[str]        # 发生变更的文件路径列表

    # ─── 分析阶段输出 ───
    analysis_result: str            # LLM 素材分析结果（JSON 字符串）

    # ─── 大纲生成阶段 ───
    current_outline: Optional[OutlineDocument]  # 已有大纲（增量模式）
    proposed_chapters: list[ChapterEntry]        # LLM 提议的新章节列表

    # ─── 最终输出 ───
    final_outline: Optional[OutlineDocument]     # 最终大纲文档
    changes_made: list[OutlineChange]            # 本次运行的变更记录

    # ─── 状态控制 ───
    status: AgentStatus             # Agent 运行状态
    error_message: str              # 错误信息
```

### 5.2 LangGraph 执行图

**文件：** `src/agents/biography_outline_graph.py`

```
┌─────────┐     ┌────────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ scan_kb │────▶│ analyze_materials  │────▶│ generate_outline │────▶│ diff_and_update  │──▶ END
└─────────┘     └────────────────────┘     └──────────────────┘     └──────────────────┘
     │
     │ has_changes == False
     │
     └──────────────────────────────────────────────────────────────────────────────────────▶ END
```

**条件边说明：**

- `should_continue_after_scan`：扫描完知识库后，如果 `has_changes == False`（KB 内容哈希未变），则直接跳到 `END`，避免无意义的 LLM 调用

**图构建代码：**

```python
def build_biography_outline_graph(agent: "BiographyOutlineAgent"):
    graph = StateGraph(OutlineAgentState)

    # 注册节点
    graph.add_node("scan_kb", agent.scan_kb_node)
    graph.add_node("analyze_materials", agent.analyze_materials_node)
    graph.add_node("generate_outline", agent.generate_outline_node)
    graph.add_node("diff_and_update", agent.diff_and_update_node)

    # 入口点
    graph.set_entry_point("scan_kb")

    # 条件边：扫描后判断是否有变更
    graph.add_conditional_edges(
        "scan_kb",
        agent.should_continue_after_scan,
        {"continue": "analyze_materials", "end": END},
    )

    # 线性边
    graph.add_edge("analyze_materials", "generate_outline")
    graph.add_edge("generate_outline", "diff_and_update")
    graph.add_edge("diff_and_update", END)

    return graph.compile()
```

### 5.3 节点详解

#### 节点 1：scan_kb — 扫描知识库

**目的：** 扫描知识库，检测是否有新增/变更文件，解析所有材料，加载已有大纲。

**读取的状态字段：**（无 — 此为首个节点，仅使用配置字段）

**处理逻辑：**

```
1. 从 .state.json 加载上次运行状态（BiographyState）
2. 计算当前知识库的 SHA256 哈希
3. 对比哈希：
   - 如果相同 → 返回 {has_changes: False, status: COMPLETED}
   - 如果不同 → 继续
4. 检测具体变更的文件列表（detect_changes）
5. 调用 material_analyzer.scan_and_parse_all() 解析所有材料
6. 加载已有 outline.yaml（如果存在）
```

**更新的状态字段：**
- `events`、`people`、`timeline`、`raw_materials_text`
- `has_changes`、`changed_files`
- `current_outline`

**LLM 调用：** 无

#### 节点 2：analyze_materials — LLM 材料分析

**目的：** 调用 LLM 分析素材，提取主题、叙事弧线、人物关系、阶段分组。

**读取的状态字段：**
- `raw_materials_text`：格式化后的材料文本
- `current_outline`：已有大纲（提取已知主题）

**处理逻辑：**

```
1. 从 current_outline 中提取已有主题列表（去重后拼接为字符串）
2. 调用 LLM，模板名 = "biography_material_analyzer"
3. 如果 LLM 调用失败 → 设置 status=FAILED，返回错误信息
4. 成功 → 将分析结果（JSON 字符串）存入 analysis_result
```

**更新的状态字段：**
- `analysis_result`（或 `status` + `error_message`）

**LLM 调用：**

| 模板名 | 变量 | 说明 |
|--------|------|------|
| `biography_material_analyzer` | `materials_content`: 格式化材料文本<br>`existing_themes`: 已有主题（逗号分隔） | 分析素材，输出 JSON 格式的主题/弧线/关系/分组 |

#### 节点 3：generate_outline — LLM 生成大纲

**目的：** 基于分析结果，调用 LLM 生成章节结构。

**读取的状态字段：**
- `analysis_result`：素材分析 JSON
- `current_outline`：已有大纲（增量模式下传入）

**处理逻辑：**

```
1. 将 current_outline 序列化为 YAML 文本（如果存在）
2. 扫描所有可用的知识库文件路径列表
3. 调用 LLM，模板名 = "biography_outline_planner"
4. 解析 LLM 返回的 JSON 数组（支持 ```json 代码块包裹）
5. 将每个 JSON 对象反序列化为 ChapterEntry
6. 如果解析失败 → 设置 status=FAILED
```

**更新的状态字段：**
- `proposed_chapters`（或 `status` + `error_message`）

**LLM 调用：**

| 模板名 | 变量 | 说明 |
|--------|------|------|
| `biography_outline_planner` | `analysis_result`: 分析结果 JSON<br>`existing_outline`: 已有大纲 YAML<br>`available_materials`: 可用文件列表 | 生成章节大纲，输出 JSON 数组 |

#### 节点 4：diff_and_update — 对比更新大纲

**目的：** 将 LLM 提议的章节与已有大纲合并，写入文件系统。

**读取的状态字段：**
- `current_outline`：已有大纲
- `proposed_chapters`：LLM 提议的新章节
- `changed_files`：变更的文件列表

**处理逻辑：**

```
如果 current_outline 存在（增量模式）:
  1. 深拷贝已有大纲
  2. 遍历 proposed_chapters:
     - 如果 chapter_id 不在已有章节中 → 标记为 DRAFT，追加到大纲
     - 记录 OutlineChange(action="add")
  3. 遍历已有章节:
     - 如果状态是 WRITTEN 且 source_materials 中有文件在 changed_files 中
       → 标记为 OUTDATED
       → 记录 OutlineChange(action="mark_outdated")
  4. 版本号 +1，更新 last_updated

如果 current_outline 不存在（首次运行）:
  1. 创建新的 OutlineDocument
  2. 所有章节标记为 DRAFT
  3. 记录所有 OutlineChange(action="add", reason="首次生成大纲")

保存文件:
  1. save_outline(final_outline) → 写入 outline.yaml
  2. save_state(new_state) → 写入 .state.json
```

**更新的状态字段：**
- `final_outline`、`changes_made`、`status`

**LLM 调用：** 无

### 5.4 增量更新机制

OutlineAgent 支持增量更新，避免在知识库无变化时重复处理。

**变更检测流程：**

```
                ┌──────────────────┐
                │   加载 .state.json  │
                │  (prev_kb_hash)    │
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │ compute_kb_hash() │
                │ SHA256(所有KB文件) │
                └────────┬─────────┘
                         │
                    哈希相同？
                   ╱         ╲
                 是             否
                 │              │
                 ▼              ▼
          ┌──────────┐   ┌──────────────┐
          │ 跳过处理  │   │ detect_changes│
          │ 直接 END  │   │ 找出新增文件  │
          └──────────┘   └──────┬───────┘
                                │
                                ▼
                         继续完整流程
```

**哈希计算方式：**
- 遍历 `events/`、`people/`、`timeline/`、`themes/` 下所有 `.md` 文件
- 按路径字典序排序
- 依次将 `路径` + `文件内容` 喂入 SHA256 hasher
- 输出 64 字符十六进制哈希

**增量大纲更新规则：**

| 场景 | 处理方式 |
|------|---------|
| 新增知识库文件 | LLM 可能提议新章节，标记为 `DRAFT` |
| 已有 `CONFIRMED` 章节 | 保持不变 |
| 已有 `WRITTEN` 章节，源材料未变 | 保持不变 |
| 已有 `WRITTEN` 章节，源材料有变 | 标记为 `OUTDATED` |
| 已有 `DRAFT` 章节 | 可被 LLM 重新提议覆盖 |

### 5.5 LLM Prompts

#### biography_material_analyzer

**模板名：** `biography_material_analyzer`

**角色定位：** 资深的传记文学编辑与叙事分析专家

**输入变量：**
- `${materials_content}`：知识库素材的格式化文本（事件+人物+时间线）
- `${existing_themes}`：已识别的主题列表（首次运行时为空）

**分析维度：**
1. 主题提取（家庭亲情、个人成长、事业奋斗、困境韧性等）
2. 叙事弧线发现（起因→发展→冲突→结果）
3. 人物关系梳理
4. 人生阶段分组
5. 传记方法论视角（冲突点、转折点、成长模式、情感高潮）

**输出格式（JSON）：**

```json
{
  "themes": ["主题1", "主题2"],
  "narrative_arcs": [
    {
      "title": "叙事弧名称",
      "description": "核心内容描述",
      "life_stages": ["childhood", "youth"],
      "key_events": ["事件标题1", "事件标题2"]
    }
  ],
  "character_relationships": [
    {
      "person": "人名",
      "relationship": "关系",
      "significance": "重要性描述",
      "related_events": ["相关事件"]
    }
  ],
  "life_stage_groupings": {
    "childhood": {"events": [...], "themes": [...], "emotional_tone": "..."},
    "youth": {...},
    "middle_age": {...},
    "elderly": {...}
  }
}
```

#### biography_outline_planner

**模板名：** `biography_outline_planner`

**角色定位：** 经验丰富的传记大纲策划师，专注口述自传结构设计

**输入变量：**
- `${analysis_result}`：素材分析结果的 JSON 字符串
- `${existing_outline}`：当前已有的大纲内容（YAML 格式，首次为空）
- `${available_materials}`：可用素材文件路径列表

**设计原则：**
- 时间为主轴 + 主题为章节的混合结构
- 首章为"引子/序曲"，末章为"回望/感悟"
- 每章至少对应 2-3 个事件素材
- 增量模式下不修改 `confirmed`/`written` 章节

**输出格式（JSON 数组）：**

```json
[
  {
    "id": "ch01",
    "title": "章节标题",
    "life_stage": "childhood",
    "theme": "核心主题",
    "source_materials": ["events/childhood/file1.md"],
    "summary": "50-100字的章节概述"
  }
]
```

---

## 六、BiographyWritingAgent 架构

### 6.1 State 模型 (WritingAgentState)

**文件：** `src/models/biography_writing_state.py`

```python
class WritingAgentState(BaseModel):
    """传记写作 Agent 的 LangGraph 状态"""

    # ─── 配置 ───
    user_id: str                        # 用户标识
    kb_path: str                        # 知识库路径
    biography_path: str                 # 传记输出目录路径

    # ─── 任务队列 ───
    chapters_to_write: list[ChapterTask]  # 待写作任务列表
    current_chapter: Optional[ChapterTask]  # 当前正在处理的章节
    current_chapter_index: int            # 当前章节在队列中的索引

    # ─── 当前写作的工作数据 ───
    source_content: str                 # 当前章节的源材料完整内容
    character_profiles: str             # 相关人物信息文本
    timeline_context: str               # 时间线上下文文本

    # ─── 写作输出 ───
    draft_content: str                  # 当前章节的 LLM 初稿
    reviewed_content: str               # 审阅后的最终内容

    # ─── 完成追踪 ───
    completed_chapters: list[str]       # 已完成的 chapter_id 列表

    # ─── 状态控制 ───
    status: AgentStatus                 # Agent 运行状态
    error_message: str                  # 错误信息
```

### 6.2 LangGraph 执行图

**文件：** `src/agents/biography_writing_graph.py`

```
                                      ┌─────────────────┐
                                      │                 │
┌────────────┐    ┌───────────────┐   │  ┌───────────┐  │   ┌────────────────┐
│ load_tasks │───▶│gather_materials│──▶│  │write_chapter│──▶│review_and_save │
└────────────┘    └───────────────┘   │  └───────────┘  │   └───────┬────────┘
      │                               │                 │           │
      │ 无任务                         └─────────────────┘           │
      │                                                             │
      ▼                              还有章节？                should_continue
     END ◀──── merge_biography ◀───── merge ────────────────── continue ──▶ gather_materials
                                                                              (循环回去)
```

**详细流程图（含条件边）：**

```
                    ┌────────────┐
                    │ load_tasks │
                    └─────┬──────┘
                          │
                 should_continue_after_load
                   ╱              ╲
             "end"                 "continue"
               │                      │
               ▼                      ▼
              END              ┌──────────────────┐
                               │ gather_materials  │◀──────────────┐
                               └────────┬─────────┘               │
                                        │                         │
                                        ▼                         │
                               ┌────────────────┐                 │
                               │ write_chapter   │                │
                               └────────┬───────┘                 │
                                        │                         │
                                        ▼                         │
                               ┌─────────────────┐               │
                               │ review_and_save  │               │
                               └────────┬────────┘               │
                                        │                         │
                                  should_continue                 │
                                 ╱            ╲                   │
                          "merge"              "continue" ────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ merge_biography │
                    └────────┬────────┘
                             │
                             ▼
                            END
```

**图构建代码：**

```python
def build_biography_writing_graph(agent: "BiographyWritingAgent"):
    graph = StateGraph(WritingAgentState)

    graph.add_node("load_tasks", agent.load_tasks_node)
    graph.add_node("gather_materials", agent.gather_materials_node)
    graph.add_node("write_chapter", agent.write_chapter_node)
    graph.add_node("review_and_save", agent.review_and_save_node)
    graph.add_node("merge_biography", agent.merge_biography_node)

    graph.set_entry_point("load_tasks")

    # 加载后判断是否有待写任务
    graph.add_conditional_edges(
        "load_tasks",
        agent.should_continue_after_load,
        {"continue": "gather_materials", "end": END},
    )

    graph.add_edge("gather_materials", "write_chapter")
    graph.add_edge("write_chapter", "review_and_save")

    # 审阅保存后判断是否还有下一章
    graph.add_conditional_edges(
        "review_and_save",
        agent.should_continue,
        {"continue": "gather_materials", "merge": "merge_biography"},
    )

    graph.add_edge("merge_biography", END)
    return graph.compile()
```

### 6.3 节点详解

#### 节点 1：load_tasks — 加载写作任务

**目的：** 从 `outline.yaml` 中筛选所有 `status == "confirmed"` 的章节，构建写作任务队列。

**读取的状态字段：** 无（使用配置字段）

**处理逻辑：**

```
1. 加载 outline.yaml
2. 如果不存在 → status=COMPLETED, error_message="未找到大纲文件"
3. 筛选 status == CONFIRMED 的章节
4. 如果没有已确认章节 → status=COMPLETED（无任务）
5. 构建 ChapterTask 列表
6. 设置 current_chapter = tasks[0], current_chapter_index = 0
```

**更新的状态字段：**
- `chapters_to_write`、`current_chapter`、`current_chapter_index`

**LLM 调用：** 无

#### 节点 2：gather_materials — 收集写作材料

**目的：** 为当前章节收集源材料内容、相关人物档案和时间线上下文。

**读取的状态字段：**
- `current_chapter`：当前章节任务

**处理逻辑：**

```
1. 调用 material_analyzer.gather_chapter_materials()
   - 读取 source_materials 列表中的所有文件
   - 从文件内容中提取 wiki link 引用的人物名
   - 匹配人物档案
   - 筛选对应 life_stage 的时间线条目
2. 返回 {source_content, character_profiles, timeline_context}
```

**更新的状态字段：**
- `source_content`、`character_profiles`、`timeline_context`

**LLM 调用：** 无

#### 节点 3：write_chapter — LLM 撰写章节

**目的：** 调用 LLM 生成第一人称口述体散文初稿。

**读取的状态字段：**
- `current_chapter`：章节信息（标题、主题、阶段）
- `source_content`：源材料内容
- `character_profiles`：人物信息
- `timeline_context`：时间线上下文

**处理逻辑：**

```
1. 调用 LLM，模板名 = "biography_chapter_writer"
2. 如果调用失败 → status=FAILED
3. 成功 → 存储初稿到 draft_content
```

**更新的状态字段：**
- `draft_content`（或 `status` + `error_message`）

**LLM 调用：**

| 模板名 | 变量 | 说明 |
|--------|------|------|
| `biography_chapter_writer` | `chapter_title`：章节标题<br>`chapter_theme`：主题<br>`life_stage`：人生阶段<br>`source_materials`：源材料<br>`character_profiles`：人物信息<br>`timeline_context`：时间线 | 生成 1500-3000 字的口述体散文 |

#### 节点 4：review_and_save — 审阅并保存

**目的：** LLM 审阅初稿质量，决定是否修订，然后保存章节并推进到下一章。

**读取的状态字段：**
- `current_chapter`：章节信息
- `draft_content`：初稿内容
- `source_content`：源材料（用于事实核对）
- `chapters_to_write`：任务队列
- `current_chapter_index`：当前索引
- `completed_chapters`：已完成列表

**处理逻辑：**

```
1. 调用 LLM 审阅，模板名 = "biography_chapter_reviewer"
2. 解析审阅结果 JSON:
   - score: 评分（1-10）
   - issues: 问题列表
   - needs_revision: 是否需要修订
   - revised_content: 修订后内容
3. 决定使用初稿还是修订版:
   - needs_revision==True 且有 revised_content → 使用修订版
   - 否则 → 使用初稿
4. 如果审阅 LLM 调用失败或 JSON 解析失败 → 降级使用初稿
5. 保存章节文件: file_manager.save_chapter()
6. 更新 outline.yaml: 该章节 status → WRITTEN, written_at → now()
7. 推进任务队列: current_chapter_index += 1
```

**更新的状态字段：**
- `reviewed_content`、`completed_chapters`、`current_chapter_index`、`current_chapter`

**LLM 调用：**

| 模板名 | 变量 | 说明 |
|--------|------|------|
| `biography_chapter_reviewer` | `chapter_content`：待审初稿<br>`source_materials`：原始素材<br>`chapter_title`：章节标题 | 审校质量，输出 JSON 评分+问题+修订 |

#### 节点 5：merge_biography — 合并完整传记

**目的：** 所有章节写作完成后，合并为一份完整的传记文件。

**读取的状态字段：** 无（直接从文件系统读取）

**处理逻辑：**

```
1. 加载 outline.yaml
2. 调用 file_manager.merge_chapters_to_full(outline)
3. 生成 full_biography.md（含目录、锚点、所有章节内容）
```

**更新的状态字段：**
- `status` → `COMPLETED`

**LLM 调用：** 无

#### 条件边函数

**`should_continue_after_load`：**

```python
def should_continue_after_load(self, state: WritingAgentState) -> str:
    if not state.chapters_to_write:
        return "end"       # 无待写章节，直接结束
    return "continue"      # 有任务，开始写作循环
```

**`should_continue`：**

```python
def should_continue(self, state: WritingAgentState) -> str:
    if state.current_chapter_index < len(state.chapters_to_write):
        return "continue"  # 还有章节，循环回 gather_materials
    return "merge"         # 全部完成，进入合并
```

### 6.4 写作风格控制

WritingAgent 通过 `biography_chapter_writer` Prompt 严格控制写作风格：

**第一人称口述体要求：**
- 全篇使用第一人称"我"进行叙述
- 像老人坐在身旁对你讲述往事
- 自然的语气词和停顿（"你说怪不怪"、"唉"、"那会儿啊"）

**"Show, Don't Tell" 原则：**
- 用具体的声音、气味、触感、温度代替抽象描述
- ❌ "那时候生活很艰苦"
- ✅ "冬天没有棉鞋，脚趾冻得通红，踩在地上跟踩在刀子上似的"

**老年人声音保持：**
- 允许模糊记忆的表达："我记得那是个冬天..."
- 自然的回忆过渡语："现在想起来..."、"那时候哪知道..."
- 保持老年人回忆时的感慨和温度

**记忆空白处理：**
- 情感真实高于事实精确
- 允许模糊表达："具体是哪一年我记不清了，但那时候..."
- 不编造素材中不存在的重要事实
- 可以合理补充感官细节和环境描写

**结构要求：**
- 开头：鲜明的记忆片段或感官细节切入
- 主体：事件自然串联，穿插反思，可像聊天一样跳跃
- 结尾：连接过去与现在的反思性段落

**字数控制：** 1500-3000 中文字符/章

### 6.5 自我审阅机制

WritingAgent 内置 LLM 审阅环节，由 `biography_chapter_reviewer` Prompt 驱动。

**审阅维度（6 个）：**

| 维度 | 英文标识 | 检查内容 |
|------|---------|---------|
| 声音一致性 | Voice Consistency | 全篇是否像同一位老人讲话 |
| 事实对齐 | Factual Alignment | 文中事实是否有素材依据 |
| 叙事流畅度 | Narrative Flow | 段落过渡是否自然 |
| 情感真实性 | Emotional Authenticity | 情感表达是否自然可信 |
| 感官丰富度 | Sensory Richness | 是否有足够具体细节 |
| 无中生有检测 | No Fabrication | 是否编造了不存在的事实 |

**评分标准：**

| 分数范围 | 级别 | 处理 |
|----------|------|------|
| 9-10 | 优秀 | 无需修改 |
| 7-8 | 良好 | 小问题，不强制修改 |
| 5-6 | 及格 | 需要修改 |
| 3-4 | 较差 | 大幅修改 |
| 1-2 | 不合格 | 重写 |

**修订判定规则：**

```
如果 score >= 7 且 没有 fabrication 类型问题:
    → needs_revision = false（使用初稿）
如果 score < 7 或 存在 fabrication 类型问题:
    → needs_revision = true（提供修订版本）
```

**降级策略（Fallback）：**

```
审阅 LLM 调用失败:
    → 打印警告日志
    → 使用初稿作为最终内容

审阅结果 JSON 解析失败:
    → 打印警告日志
    → 使用初稿作为最终内容
```

**审阅输出格式（JSON）：**

```json
{
  "score": 8,
  "issues": [
    {
      "type": "fabrication|inconsistency|flow|voice",
      "description": "问题描述",
      "location": "相关文字片段"
    }
  ],
  "suggestions": ["建议1", "建议2"],
  "needs_revision": false,
  "revised_content": ""
}
```

### 6.6 LLM Prompts

#### biography_chapter_writer

**模板名：** `biography_chapter_writer`

**角色定位：** 资深传记文学作家，擅长第一人称口述体散文

**输入变量：**

| 变量名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| `${chapter_title}` | string | 章节规划 | 章节标题 |
| `${chapter_theme}` | string | 章节规划 | 章节主题焦点 |
| `${life_stage}` | string | 章节规划 | 人生阶段 |
| `${source_materials}` | string | 知识库文件 | 所有源文件完整内容 |
| `${character_profiles}` | string | 人物档案 | 相关人物信息 |
| `${timeline_context}` | string | 时间线 | 时间线上下文 |

**输出格式：** 纯 Markdown 散文文本，以 `# 标题` 开头，1500-3000 字

#### biography_chapter_reviewer

**模板名：** `biography_chapter_reviewer`

**角色定位：** 严谨的传记文学编辑

**输入变量：**

| 变量名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| `${chapter_content}` | string | 写作 Agent 输出 | 待审校的章节正文 |
| `${source_materials}` | string | 知识库文件 | 原始素材（用于事实核对） |
| `${chapter_title}` | string | 章节规划 | 章节标题 |

**输出格式：** JSON 对象，包含 `score`、`issues`、`suggestions`、`needs_revision`、`revised_content`

---

## 七、数据流与交互序列

### 7.1 完整工作流时序图

```
  知识库(KB)          OutlineAgent               文件系统                用户              WritingAgent
     │                    │                        │                    │                    │
     │    scan_kb_node    │                        │                    │                    │
     │◀───── 扫描文件 ─────│                        │                    │                    │
     │──── 返回内容 ──────▶│                        │                    │                    │
     │                    │                        │                    │                    │
     │              analyze_materials              │                    │                    │
     │                    │──── LLM 调用 ──▶        │                    │                    │
     │                    │◀── 分析结果 ───         │                    │                    │
     │                    │                        │                    │                    │
     │              generate_outline               │                    │                    │
     │                    │──── LLM 调用 ──▶        │                    │                    │
     │                    │◀── 章节 JSON ──         │                    │                    │
     │                    │                        │                    │                    │
     │              diff_and_update                │                    │                    │
     │                    │──── save ──────────────▶│                    │                    │
     │                    │        outline.yaml     │                    │                    │
     │                    │        .state.json      │                    │                    │
     │                    │                        │                    │                    │
     │                    │                        │  查看 outline.yaml  │                    │
     │                    │                        │◀───── 阅读 ─────────│                    │
     │                    │                        │                    │                    │
     │                    │                        │   修改 status:      │                    │
     │                    │                        │   draft → confirmed│                    │
     │                    │                        │◀──── 编辑保存 ──────│                    │
     │                    │                        │                    │                    │
     │                    │                        │                    │   启动 WritingAgent │
     │                    │                        │                    │──────────────────▶│
     │                    │                        │                    │                    │
     │                    │                        │   load_tasks       │                    │
     │                    │                        │◀──── 读取 ─────────│────────────────────│
     │                    │                        │   outline.yaml     │                    │
     │                    │                        │─── confirmed ──────│───────────────────▶│
     │                    │                        │                    │                    │
     │                    │                        │                    │    [循环每章]       │
     │    gather_materials│                        │                    │                    │
     │◀───── 读取源文件 ──────────────────────────────────────────────────────────────────────│
     │──── 返回内容 ──────────────────────────────────────────────────────────────────────────▶│
     │                    │                        │                    │                    │
     │                    │                        │                    │  write_chapter     │
     │                    │                        │                    │  ── LLM 调用 ──▶   │
     │                    │                        │                    │  ◀── 初稿 ───      │
     │                    │                        │                    │                    │
     │                    │                        │                    │  review_and_save   │
     │                    │                        │                    │  ── LLM 审阅 ──▶   │
     │                    │                        │                    │  ◀── 评分+修订 ──   │
     │                    │                        │                    │                    │
     │                    │                        │◀── 保存章节 ──────────────────────────────│
     │                    │                        │  chapters/ch01.md  │                    │
     │                    │                        │◀── 更新 status ─────────────────────────│
     │                    │                        │  outline.yaml      │                    │
     │                    │                        │  (WRITTEN)         │                    │
     │                    │                        │                    │    [循环结束]       │
     │                    │                        │                    │                    │
     │                    │                        │   merge_biography  │                    │
     │                    │                        │◀── 合并 ───────────────────────────────│
     │                    │                        │  full_biography.md │                    │
```

### 7.2 增量工作流

```
  ┌────────────────────────────────────────────────────────────────────────────┐
  │                         增量更新场景                                        │
  │                                                                            │
  │  1. 新增采访 → 知识库更新                                                   │
  │     events/elderly/新事件.md (新增)                                         │
  │                                                                            │
  │  2. OutlineAgent 检测变更                                                   │
  │     compute_kb_hash() != .state.json.kb_content_hash                       │
  │     → 检测到 1 个新增文件                                                   │
  │                                                                            │
  │  3. LLM 分析 + 规划                                                        │
  │     → 提议新增 ch06: "晚年的花园" (DRAFT)                                  │
  │     → 发现 ch03 的源材料 events/middle_age/xxx.md 被修改                    │
  │       → ch03 标记为 OUTDATED                                               │
  │                                                                            │
  │  4. 用户审阅 outline.yaml                                                  │
  │     → 确认 ch06 (DRAFT → CONFIRMED)                                        │
  │     → 可选: 确认 ch03 重写 (OUTDATED → CONFIRMED)                          │
  │                                                                            │
  │  5. WritingAgent 写作                                                       │
  │     → 只写 ch06（和可能的 ch03）                                            │
  │     → 已有的 ch01-ch05 不受影响                                             │
  │                                                                            │
  │  6. 合并输出                                                                │
  │     → full_biography.md 包含所有章节（新旧合并）                            │
  └────────────────────────────────────────────────────────────────────────────┘
```

---

## 八、依赖注入与组件关系

### 8.1 类依赖关系图

```
┌──────────────────────────────────────────────────────────────┐
│                        应用层                                │
│                                                              │
│  ┌──────────────────────┐    ┌──────────────────────────┐   │
│  │ BiographyOutlineAgent │    │ BiographyWritingAgent     │   │
│  │                      │    │                          │   │
│  │ - llm_service        │    │ - llm_service            │   │
│  │ - file_manager       │    │ - file_manager           │   │
│  │ - material_analyzer  │    │ - material_analyzer      │   │
│  └──────────┬───────────┘    └──────────┬───────────────┘   │
│             │                           │                    │
│             │     依赖注入               │                    │
│             ▼                           ▼                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                     服务层                             │   │
│  │                                                      │   │
│  │  ┌─────────────┐  ┌────────────────────┐             │   │
│  │  │ LLMService   │  │BiographyFileManager│             │   │
│  │  │              │  │                    │             │   │
│  │  │ - config     │  │ - kb_path          │             │   │
│  │  │ - templates  │  │ - biography_path   │             │   │
│  │  └──────────────┘  └─────────┬──────────┘             │   │
│  │                              │                        │   │
│  │                              │ 依赖                    │   │
│  │                              ▼                        │   │
│  │               ┌──────────────────────────┐            │   │
│  │               │BiographyMaterialAnalyzer │            │   │
│  │               │                          │            │   │
│  │               │ - file_manager           │            │   │
│  │               └──────────────────────────┘            │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                     配置层                             │   │
│  │                                                      │   │
│  │  ┌─────────────┐                                     │   │
│  │  │ LLMConfig    │                                     │   │
│  │  │              │                                     │   │
│  │  │ - provider   │                                     │   │
│  │  │ - model_name │                                     │   │
│  │  │ - api_key    │                                     │   │
│  │  │ - base_url   │                                     │   │
│  │  │ - temperature│                                     │   │
│  │  │ - max_tokens │                                     │   │
│  │  └─────────────┘                                     │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 8.2 依赖注入模式

两个 Agent 的构造参数完全相同，遵循统一的依赖注入模式：

```python
# 1. 配置
config = LLMConfig(
    provider="deepseek",
    model_name="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_APIKEY", ""),
    base_url=os.getenv("DEEPSEEK_URL", ""),
    temperature=0.7,   # OutlineAgent 用 0.7，WritingAgent 用 0.8
    max_tokens=4096,
)

# 2. 服务实例化（自底向上）
llm_service = LLMService(config)
file_manager = BiographyFileManager(kb_path="knowledge_base/test_user001")
material_analyzer = BiographyMaterialAnalyzer(file_manager)

# 3. Agent 实例化
outline_agent = BiographyOutlineAgent(
    llm_service=llm_service,
    file_manager=file_manager,
    material_analyzer=material_analyzer,
)

writing_agent = BiographyWritingAgent(
    llm_service=llm_service,
    file_manager=file_manager,
    material_analyzer=material_analyzer,
)

# 4. 运行（async）
outline_state = await outline_agent.run(user_id="user001", kb_path=kb_path)
# ... 用户确认章节 ...
writing_state = await writing_agent.run(user_id="user001", kb_path=kb_path)
```

**设计要点：**
- `BiographyMaterialAnalyzer` 依赖 `BiographyFileManager`，不直接操作文件
- 两个 Agent 可以共享同一套服务实例
- `LLMConfig.temperature` 可按场景调整：OutlineAgent 用 0.7（更稳定），WritingAgent 用 0.8（更有创意）
- Agent 的 `run()` 方法内部延迟导入图构建函数，避免循环依赖

---

## 九、错误处理策略

### 9.1 LLM 调用失败

每个 LLM 调用节点都实现了独立的错误处理：

```python
result = await self.llm_service.invoke_with_template(...)

if not result.success:
    logger.error(f"LLM 调用失败: {result.error}")
    return {
        "status": AgentStatus.FAILED,
        "error_message": f"xxx失败: {result.error}",
    }
```

- **OutlineAgent**：`analyze_materials_node` 和 `generate_outline_node` 失败时设置 `status=FAILED`，图终止
- **WritingAgent**：`write_chapter_node` 失败时设置 `status=FAILED`，图终止

### 9.2 JSON 解析失败

LLM 输出的 JSON 可能格式异常，系统做了多层防御：

```python
# 1. 支持 ```json 代码块包裹
if "```json" in content:
    content = content.split("```json")[1].split("```")[0].strip()
elif "```" in content:
    content = content.split("```")[1].split("```")[0].strip()

# 2. 标准 JSON 解析
chapters_data = json.loads(content)

# 3. Pydantic 验证
proposed_chapters = [ChapterEntry.model_validate(ch) for ch in chapters_data]
```

- **OutlineAgent `generate_outline_node`**：解析失败 → `status=FAILED`，图终止
- **WritingAgent `review_and_save_node`**：解析失败 → 降级使用初稿（不终止）

### 9.3 文件 I/O 错误

`BiographyFileManager` 中的文件操作通过 try/except 捕获异常：

- **关键文件操作**（`load_outline`、`save_outline`、`load_state`、`save_state`）：异常向上抛出
- **批量读取**（`read_kb_files_by_paths`）：单个文件失败时跳过并记录警告，不影响其他文件
- **哈希计算**（`compute_kb_hash`）：单个文件读取失败时跳过

### 9.4 审阅降级策略

WritingAgent 的审阅环节采用"最大努力"策略，确保即使审阅失败也能产出内容：

```
┌────────────────┐
│ 调用审阅 LLM    │
└───────┬────────┘
        │
   调用成功？
   ╱       ╲
  否         是
  │          │
  │     JSON 解析成功？
  │     ╱          ╲
  │   否            是
  │   │              │
  │   │         需要修订 且
  │   │         有修订内容？
  │   │         ╱       ╲
  │   │       否          是
  │   │       │           │
  ▼   ▼       ▼           ▼
  使用初稿    使用初稿    使用修订版
  (fallback) (fallback)  (最优路径)
```

**核心原则：** 初稿永远作为兜底，保证每个章节都有产出。
