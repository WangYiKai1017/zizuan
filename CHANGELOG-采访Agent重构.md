# 采访 Agent 系统重构 CHANGELOG

> **版本**: v2.0.0
> **日期**: 2026-06-01
> **范围**: Agent 服务化 + 采访 Agent 子系统系统性重构
> **作者**: Engineering Team

---

## 概览

本次会话包含两轮独立但互相衔接的代码变更：

| 轮次 | 主题 | 分支 | 关键产出 |
|------|------|------|---------|
| **Round 1** | Agent 服务化 | `service` | FastAPI + SSE 服务层，4 个 Agent 全部 HTTP 化 |
| **Round 2** | 采访 Agent 重构 | `interview-refactor` | 8 个任务 + 1 个缺陷修复 + 53 项单元测试 |

两轮变更共同实现了：将原本以脚本/CLI 形式存在的 4 个 LangGraph Agent，升级为可云端部署、流式响应、按用户隔离、且具备会话恢复与动态对话深度控制能力的服务化 Agent 系统。

---

## Round 1 — Agent 服务化（Service Layer）

### 目标
将 4 个独立 Agent（采访 Agent、知识库整理 Agent、传记大纲 Agent、传记写作 Agent）统一封装为可通过 HTTP/SSE 调用的后端服务，支持云端一键部署，并通过全局会话管理保证用户级别的并发安全。

### 架构图

```
┌──────────────────────────────────────────────────────────┐
│                      FastAPI App                         │
│   (CORS / Lifespan / Router 注册 / 全局错误处理)         │
└──────────────┬──────────────┬──────────────┬─────────────┘
               │              │              │
       ┌───────▼──────┐ ┌─────▼─────┐ ┌──────▼──────┐
       │  Routes 层   │ │  Schemas  │ │  Files API  │
       │ /interview   │ │ Pydantic  │ │  read/list  │
       │ /kb_organizer│ │ Requests  │ │             │
       │ /outline     │ └───────────┘ └─────────────┘
       │ /writing     │
       └───────┬──────┘
               │ depends on
       ┌───────▼─────────────────┐
       │   AgentRunner 抽象层    │
       │  BaseRunner ──┬─────────┤
       │               ├─ Interview      │
       │               ├─ KBOrganizer    │
       │               ├─ Outline        │
       │               └─ Writing        │
       └───────┬─────────────────┘
               │ uses
       ┌───────▼─────────┐  ┌──────────────────┐
       │  SSEEmitter     │  │ SessionManager   │
       │  sse_response   │  │  (全局单例)      │
       │  统一流式封装   │  │  Per-User 互斥   │
       └─────────────────┘  └──────────────────┘
```

### 关键交付物

#### 1. 服务核心组件
- **`src/service/app.py`** — FastAPI 应用装配，注册 4 个 Agent 路由 + 文件路由，配置 CORS 与 lifespan。
- **`src/service/session_manager.py`** — 全局单例 `SessionManager`，确保**同一用户同一时刻只允许一个 Agent 运行**。
- **`src/service/sse_response.py`** — `SSEEmitter` 统一 SSE 流式响应封装，规范事件格式（`session_id` / `chunk` / `done` / `error`）。
- **`src/service/schemas/requests.py`** — 所有路由共享的请求体 Pydantic 模型。

#### 2. Agent Runner 层（OOP 封装）
| 文件 | 作用 |
|------|------|
| `src/service/agent_runners/base_runner.py` | 抽象基类，定义 start/resume/end 生命周期 |
| `src/service/agent_runners/interview_runner.py` | 采访 Agent 运行器 |
| `src/service/agent_runners/kb_organizer_runner.py` | 知识库整理 Agent 运行器 |
| `src/service/agent_runners/outline_runner.py` | 传记大纲 Agent 运行器 |
| `src/service/agent_runners/writing_runner.py` | 传记写作 Agent 运行器 |

#### 3. Routes 层（HTTP 端点）
- `src/service/routes/interview.py`
- `src/service/routes/kb_organizer.py`
- `src/service/routes/biography_outline.py`
- `src/service/routes/biography_writing.py`
- `src/service/routes/files.py` — 提供 KB 文件读取 / 列举接口

#### 4. 启动与部署脚本
| 脚本 | 用途 |
|------|------|
| `run_server.py` | 进程入口（uvicorn 启动 FastAPI） |
| `start_service.sh` | Shell 一键启动（自动激活 .venv） |
| `start_service.py` | Python 启动脚本（含端口检查） |
| `setup.sh` | 云端一键环境初始化 |
| `setup_env.py` | 创建 venv 并安装 requirements.txt |

#### 5. 测试体系
**单元测试（共 29 项，全部通过）**
- `tests/test_service/test_session_manager.py` — SessionManager 互斥与单例验证
- `tests/test_service/test_sse_response.py` — SSE 事件格式与流式输出
- `tests/test_service/test_file_routes.py` — 文件路由权限与路径

**集成测试（按 Agent 拆分）**
- `tests/integration/test_interview_api.py`
- `tests/integration/test_kb_organizer_api.py`
- `tests/integration/test_biography_outline_api.py`
- `tests/integration/test_biography_writing_api.py`
- `tests/integration/run_all.py` — 串联运行入口
- `tests/integration/_common.py` — SSE 解析、session_id 提取等公共工具

#### 6. 任务卡与依赖
- `开发故事卡/Task-014-Agent服务化.md` — 本轮任务设计文档
- `requirements.txt` — 新增 `fastapi`、`uvicorn`、`sse-starlette`、`httpx` 等依赖

### 验证方式
```bash
# 启动服务
./start_service.sh

# 单元测试
pytest tests/test_service/ -v

# 集成测试（需服务已启动）
python tests/integration/run_all.py
```

### Round 1 文件清单（共 31 个新增文件）

**源代码（16）**
```
src/service/__init__.py
src/service/app.py
src/service/session_manager.py
src/service/sse_response.py
src/service/schemas/requests.py
src/service/agent_runners/base_runner.py
src/service/agent_runners/interview_runner.py
src/service/agent_runners/kb_organizer_runner.py
src/service/agent_runners/outline_runner.py
src/service/agent_runners/writing_runner.py
src/service/routes/interview.py
src/service/routes/kb_organizer.py
src/service/routes/biography_outline.py
src/service/routes/biography_writing.py
src/service/routes/files.py
run_server.py
```

**部署脚本（4）**
```
start_service.sh
start_service.py
setup.sh
setup_env.py
```

**测试（10）**
```
tests/test_service/test_session_manager.py
tests/test_service/test_sse_response.py
tests/test_service/test_file_routes.py
tests/integration/test_interview_api.py
tests/integration/test_kb_organizer_api.py
tests/integration/test_biography_outline_api.py
tests/integration/test_biography_writing_api.py
tests/integration/run_all.py
tests/integration/_common.py
开发故事卡/Task-014-Agent服务化.md
```

---

## Round 2 — 采访 Agent 子系统系统性重构

### 目标
针对采访 Agent 在产品试用中暴露出的 8 类问题（时间限制不灵活、Wiki 链接路径混乱、KB Querier 调用过度、缺乏档案视图、称呼僵化、话题深度失控、会话续接缺失、缺少缺陷修复），按依赖关系拆分为 8 个任务并行/串行实施。

### 重构总览

```
┌─────────────────────────────────────────────────────────┐
│           采访 Agent 系统（重构后）                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  [InterviewSessionAgent] ◄── 前端显式 end_session()    │
│        │                                                │
│        ├─ _resume_session()  ── 读取上次 session 归档  │
│        │     ├─ 解析 next_questions / context           │
│        │     └─ 还原 topic_history                      │
│        │                                                │
│        ├─ 动态称呼计算 (爷爷/奶奶/叔叔/阿姨/先生/女士)  │
│        │                                                │
│        ├─ 话题追踪器                                    │
│        │     ├─ current_topic                           │
│        │     ├─ topic_turn_count / topic_max_turns=8    │
│        │     └─ topic_history                           │
│        │                                                │
│        ├─ [QuestionGenerator]                           │
│        │     └─ LLM 评估「继续 vs 切换」                │
│        │                                                │
│        ├─ [KnowledgeBaseQuerier] (max_iterations=7)     │
│        │     ├─ 预加载 summary_index.md 作为上下文      │
│        │     ├─ MemoryCacheTool 模糊匹配                │
│        │     └─ /biography 路径排除                     │
│        │                                                │
│        └─ [MemoryArchive] (会话结束时)                  │
│              ├─ 写入 sessions/session_{date}.md         │
│              ├─ 更新 user.md                            │
│              └─ 重新生成 summary_index.md               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Task 1 — 移除时间限制
**问题**: 原系统硬编码 15min / 10min / 5min 的会话时长，对老年用户访谈节奏不友好。

**变更**:
- 删除所有时间触发的会话终止逻辑。
- 仅通过前端**显式信号** + 新增的 `end_session()` 方法结束会话。

**涉及文件**:
- `src/agents/interview_agent.py`
- `src/agents/interview_session_agent.py`

---

### Task 2（计划编号 6）— Wiki 链接规范化
**问题**: 知识库内文件互链路径不一致，含绝对路径 / 跨用户路径 / 错误转义。

**变更**:
- `MarkdownFileManager` 新增：
  - `_normalize_wiki_link(target)` — 统一相对化处理
  - `format_wiki_link(target, label)` — 标准 Wiki 链接生成
- 所有链接以 `knowledge_base/{user_id}/` 为基准做相对路径。

**涉及文件**:
- `src/storage/markdown_file_manager.py`
- `src/services/memory_manager.py`

---

### Task 3（计划编号 7）— KB Querier 优化
**问题**: 知识库查询 Agent 迭代次数失控、命中率低、误读 `/biography` 目录。

**变更**:
| 优化点 | 实现 |
|--------|------|
| 迭代上限 | `max_iterations=7` 显式设定 |
| 上下文预加载 | Agent 启动前注入 `summary_index.md` |
| 缓存匹配 | `MemoryCacheTool` 支持模糊 / 关键词匹配 |
| 路径排除 | `list_files` / `read_file` / Prompt 全部排除 `/biography` |

**涉及文件**:
- `src/services/knowledge_base_querier.py`
- `src/tools/memory_cache_tool.py`
- `src/tools/knowledge_query_tool.py`
- `src/tools/memory_archive_tool.py`
- `Prompts/KnowledgeBaseQuerier-Prompt.md`

---

### Task 4（计划编号 2）— user.md + Summary Index 基础设施
**问题**: 缺少主角档案视图，Querier 难以定位用户基本信息。

**变更**:
- 新增方法：
  - `create_or_update_user_md(profile_info)` → 写入 `knowledge_base/{user_id}/user.md`
  - `create_or_update_summary_index()` → 扫描全部 KB 文件，生成带链接 + 简介的 `summary_index.md`
- 触发时机：
  - 知识库首次创建后
  - **每次归档完成后**自动重建
- Prompt 更新：引用 `user.md` 作为主角档案，明确 `/biography` 禁区。

**涉及文件**:
- `src/storage/markdown_file_manager.py`
- `src/tools/memory_archive_tool.py`
- `Prompts/MemoryOrganizer-Prompt.md`
- `Prompts/KnowledgeBaseQuerier-Prompt.md`

---

### Task 5（计划编号 3）— 动态称呼
**问题**: 采访 Agent 全程使用「您」，缺乏代入感。

**变更**:
- 基于 `age` / `name` / `gender` 推导称呼：
  - `>=60` 男 → 爷爷 / 女 → 奶奶
  - `40~60` 男 → 叔叔 / 女 → 阿姨
  - `<40` 男 → 先生 / 女 → 女士
- `gender` 缺失时通过 `family_status` 字段（如「育有 1 子」「丈夫」）做推断。
- 通过 Prompt 变量 `address_style` 注入到 QuestionGenerator。

**涉及文件**:
- `src/agents/interview_session_agent.py`
- `src/agents/interview_agent.py`
- `src/services/question_generator.py`
- `Prompts/QuestionGenerator-Prompt.md`

---

### Task 6（计划编号 4）— 话题深度评估与切换
**问题**: Agent 容易在单一话题上反复纠缠或过早跳转。

**变更**:
- 引入话题追踪器：
  ```python
  current_topic: str
  topic_turn_count: int
  topic_max_turns: int = 8
  topic_history: list[str]
  ```
- 触发切换条件：
  1. `topic_turn_count >= topic_max_turns`
  2. LLM 检测到话题重复 / 信息饱和
- 每轮提问前，LLM 显式评估「继续深挖 vs 切换话题」。

**涉及文件**:
- `src/agents/interview_agent.py`
- `src/services/question_generator.py`
- `Prompts/QuestionGenerator-Prompt.md`

---

### Task 7（计划编号 5）— 会话归档 + 下次问题生成
**问题**: 会话结束后丢失上下文，下次重启等于冷启动。

**变更**:
- 会话结束生成 `sessions/session_{YYYY-MM-DD}.md`，包含：
  - 摘要 / 已收集信息 / **下次问题（5-8 条）** / 未完成话题 / 上下文
- 下次问题由**专门的 LLM 调用**生成（独立 prompt）
- 移除采访过程中自动的「人生阶段」标注（仅在事后归档时使用）

**涉及文件**:
- `src/agents/interview_agent.py`
- `src/agents/interview_session_agent.py`
- `src/tools/memory_archive_tool.py`
- `src/storage/markdown_file_manager.py`
- `src/services/memory_manager.py`
- `Prompts/SessionEndGuide-Prompt.md`

---

### Task 8（计划编号 8）— 会话恢复 + 上下文续接
**问题**: 重新进入采访时无法承接上次进度。

**变更**:
- 新增 `_resume_session()`:
  1. 查找最新 session 归档
  2. 解析 `next_questions` 与 `context` 段
  3. 用解析结果初始化 `initial_candidate_questions`
  4. 还原 `topic_history`
  5. 生成有上下文的「欢迎回来」开场白

**涉及文件**:
- `src/agents/interview_session_agent.py`

---

### 缺陷修复 — `memory_manager.py` ConversationTurn 访问
- **症状**: `turn["field"]` 在 Pydantic 模型上抛 `TypeError`
- **修复**: 改为属性访问 `turn.field`

---

### 测试套件重写
- `tests/test_interview_session_agent.py` — **53 项测试**全部通过
- 覆盖：时间限制移除、Wiki 链接、动态称呼、话题切换、归档、恢复、缺陷修复

---

### Round 2 文件矩阵

#### 修改的源文件
| 文件 | 涉及任务 |
|------|---------|
| `src/agents/interview_agent.py` | T1, T5, T6, T7 |
| `src/agents/interview_session_agent.py` | T1, T5, T7, T8 |
| `src/services/question_generator.py` | T5, T6 |
| `src/services/knowledge_base_querier.py` | T3 |
| `src/services/memory_manager.py` | T2, T7, BugFix |
| `src/storage/markdown_file_manager.py` | T2, T4, T7 |
| `src/tools/memory_archive_tool.py` | T3, T4, T7 |
| `src/tools/memory_cache_tool.py` | T3 |
| `src/tools/knowledge_query_tool.py` | T3 |

#### 修改的 Prompts
| 文件 | 涉及任务 |
|------|---------|
| `Prompts/QuestionGenerator-Prompt.md` | T5, T6 |
| `Prompts/MemoryOrganizer-Prompt.md` | T4 |
| `Prompts/KnowledgeBaseQuerier-Prompt.md` | T3, T4 |
| `Prompts/SessionEndGuide-Prompt.md` | T7 |

#### 新增产物
- `knowledge_base/{user_id}/user.md`（运行时生成）
- `knowledge_base/{user_id}/summary_index.md`（运行时生成）
- `knowledge_base/{user_id}/sessions/session_{date}.md`（运行时生成）

---

## 如何验证

### 启动服务
```bash
# 首次部署
./setup.sh

# 启动
./start_service.sh
```

### 运行测试
```bash
# 服务层单元测试（Round 1）
pytest tests/test_service/ -v

# 采访 Agent 单元测试（Round 2，53 项）
pytest tests/test_interview_session_agent.py -v

# 知识库整理 Agent 集成测试（规范命令）
python3 ./tests/test_kb_organizer_agent.py

# 全部集成测试（需服务已启动）
python tests/integration/run_all.py
```

### 关键回归点检查清单
- [ ] 4 个 Agent 端点均能通过 SSE 返回 `session_id` + `chunk` + `done`
- [ ] 同一 `user_id` 启动第二个 Agent 时返回 409 冲突
- [ ] 采访 Agent 不再因为时间到点自动结束
- [ ] `knowledge_base/{user_id}/user.md` 在首次档案完成后生成
- [ ] `summary_index.md` 在每次归档后刷新
- [ ] 重新进入采访时显示「欢迎回来」并接续上次话题
- [ ] 称呼随用户画像动态变化
- [ ] 单话题轮次达到 8 后自动建议切换

---

## 依赖与环境

- **Python**: 3.10+
- **关键依赖**: `fastapi`、`uvicorn`、`sse-starlette`、`langchain>=0.1.0`、`langgraph>=0.0.20`、`pydantic>=2.0`、`loguru>=0.7.0`、`pytest>=7.0`
- **环境变量**: `DEEPSEEK_API_KEY` 等需在 `.env` 中配置（参考 `.env.example`）
- **虚拟环境**: 必须使用 `.venv`，否则启动会报 `uvicorn is not installed`

---

## 历史影响与后续

- **向前兼容**: 旧的 CLI 入口仍保留（`integration_test_new_user.py` 等），但推荐通过 HTTP API 调用。
- **数据迁移**: 已存在的 `knowledge_base/{user_id}/` 目录在首次访问时会自动补齐 `user.md` 与 `summary_index.md`。
- **后续工作建议**:
  1. 为传记大纲 / 写作 Agent 增加类似的话题追踪与会话恢复机制
  2. 沉淀 `summary_index.md` 的语义检索能力（embedding）
  3. 前端实现 `end_session()` 显式按钮 + 续接确认弹窗

---

*— END —*
