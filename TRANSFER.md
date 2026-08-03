# Transfer Document — 老人自传 Agent 系统

> 给接手同事（和 TA 的 AI）的导读文档。
> 建议阅读顺序：E2E 测试 → 业务流程 → 可观测性 → 文件索引。

---

## 一、项目概述

**定位**：帮助老人回忆并记录人生故事的 AI 系统。通过多轮采访收集记忆素材，自动生成配图故事和完整传记。

**技术栈**：Python 3.10+ / FastAPI / DeepSeek LLM（OpenAI 兼容 API） / SSE 流式通信 / Markdown 文件存储 / Langfuse 可观测

**整体流程**：
```
Profile 采集 → 多轮采访 → KB 整理 → 故事生成（配图）→ 传记大纲 → 逐章写作 → 合并传记
```

**两个核心轨道**：
- **Track A（采访 + 故事）**：交互式对话，实时收集事件、人物、时间线
- **Track B（传记）**：基于已收集的素材，批量生成结构化传记

---

## 二、从 E2E 测试理解系统（建议入口）

E2E 测试是理解整个系统最快的路径——它们按真实用户的使用顺序串起了所有核心 API。

### 2.1 Track A 测试：`tests/e2e/test_track_a_interview.py`

**测试流程**（按执行顺序）：

| 步骤 | 调用 API | 测试点 |
|------|----------|--------|
| 1. Profile Prefill | `POST /api/interview/profile/prefill` | 用户画像写入 `user.md` |
| 2. Start Interview | `POST /api/interview/start` (SSE) | 新建会话、获取 session_id |
| 3. Idempotency | `POST /api/interview/start` 重复调用 | 返回同一 session_id + `reused=true` |
| 4. 多轮对话（4轮） | `POST /api/interview/message` (SSE × 4) | 引导式采访推进、guided state 跟踪 |
| 5. End Session | `POST /api/interview/end` | 生成结构化归档、session archive 落盘 |
| 6. Summary 质量 | LLM-as-judge 评估 | 摘要不能泛泛而谈，需包含具体故事/人物 |
| 7. Restart | `POST /api/interview/start` 再次调用 | 新 session、加载上次摘要、phase=interview |
| 8. 多轮对话（10轮） | `POST /api/interview/message` (SSE × 10) | 问题切换：1-4 个预设问题应被完成 |
| 9. 最终结束 | `POST /api/interview/end` | 结束重启后的采访会话 |
| 10. 知识库整理 | `POST /api/kb-organizer/run` (SSE) | 前端 End 后流程：完成整库整理并验证结果接口 |
| 11. 故事生成 | `POST /api/stories/generate` (SSE) | 注入 16 个假事件 → 生成故事 + 封面图 + 插图 |

**关键常量**（有测试语义，不是随便定的）：
```python
PRE_ROUNDS = 4      # 重启前的轮数——测试首次采访 + 引导问题推进
RESTART_ROUNDS = 10  # 重启后的轮数——测试问题切换 + guided state 推进
```

**LLM-as-judge 机制**：用 DeepSeek 对 session summary 打分（4 个维度），防止摘要退化为"聊天很愉快"之类的空话。

**测试 persona**：林建华，68 岁，上海出生，退休教师。

### 2.2 Track B 测试：`tests/e2e/test_track_b_biography.py`

**测试流程**：

| 步骤 | 调用 API | 测试点 |
|------|----------|--------|
| 1. 生成大纲 | `POST /api/biography/outline/generate` (SSE) | 从 KB 素材生成章节大纲 |
| 2. 获取大纲 | `GET /api/biography/outline/{user_id}` | 章节字段完整性 |
| 3. 确认章节 | `PUT .../chapters/{id}/confirm` (逐个) | draft → confirmed 状态转换 |
| 4. 执行写作 | `POST /api/biography/writing/run` (SSE) | 逐章写作 + 审稿 + 合并 |
| 5. 获取章节 | `GET /api/biography/writing/{user_id}/chapters` | 文件存在、有字数 |
| 6. 获取完整传记 | `GET /api/biography/writing/{user_id}/full` | 合并内容、字数 > 0 |
| 7. 增量更新 | 新增 4 个事件 → 重新生成 | 新 draft 章节、已有章节标记 outdated |

### 2.3 测试工具：`tests/integration/_common.py`

共享工具模块，包含：
- `sse_iter(response)` — SSE 流解析器（处理 LF/CRLF）
- `start_service()` / `stop_service()` / `wait_for_health()` — 服务生命周期管理
- `section()` / `info()` / `warn()` / `err()` — 结构化日志
- `print_sse_event()` — SSE 事件美化打印

### 2.4 如何运行

```bash
# 先确保 .env 中配置了 DeepSeek API key
# E2E 测试会自动启动服务、跑完测试、关闭服务

# Track A：采访 + 故事生成
python -m pytest tests/e2e/test_track_a_interview.py -v

# Track B：传记生成
python -m pytest tests/e2e/test_track_b_biography.py -v

# 单元测试 + 集成测试（不需要 API key）
python -m pytest tests/ --ignore=tests/e2e
```

---

## 三、业务流程

### 3.1 Profile 采集

**Agent**：`src/agents/profile_collection_agent.py`

新用户的第一个对话阶段。通过自然对话收集基本信息（姓名、年龄、性别、职业、家庭状况、居住情况），写入 `user.md`。

完成后自动转入采访阶段。

### 3.2 采访（核心流程）

**涉及文件**：
- `src/agents/interview_session_agent.py` — 会话管理（start / message / end 编排）
- `src/agents/interview_agent.py` — 对话引擎（问题生成、关键信息提取、KB 查询）
- `src/agents/guided_initial_interview_controller.py` — 引导式采访控制器
- `src/services/question_generator.py` — 自由采访阶段的问题生成器
- `src/service/session_manager.py` — 会话互斥管理

**采访分两个阶段**：

**阶段 1：引导式采访（Guided）**
- 使用 `GuidedInitialInterviewController`
- 62 个预设问题（定义在 `src/config/data/initial_interview_questions.csv`），按人生阶段分组（childhood / youth / middle_age / elderly）
- 每个问题最多追问 10 次
- 默认行为是**深挖当前问题**，而不是切换话题
- 切换条件：用户明确结束 / 连续短回答 / 追问次数上限 / 用户主动跳转
- 状态持久化在 `guided_initial_state.json`

**阶段 2：自由采访（Free Interview）**
- 引导问题全部完成后进入
- 使用 `QuestionGenerator` 生成问题
- 话题追踪：每个话题最多 8 轮，超过后强制切换
- 支持候选问题（candidate_questions）注入

**每轮对话的核心流程**：
```
用户输入 → 关键信息提取（事件/人物/时间/地点）
         → 缓存查询（命中则复用）→ 未命中则查 KB → 写入缓存
         → 问题生成（guided 或 free）
         → 记录对话轮次
```

**会话管理**（`SessionManager`）：
- **互斥 slot**：同一用户同时只能运行一个独占型 agent
- 独占型：interview、kb_organizer、story_generation
- 传记型：biography_outline、biography_writing（互相排斥，但可与独占型并行）

**Session 结束时的产出**：
- `sessions/session_YYYYMMDD_HHMMSS.md` — 采访归档（摘要 + 事件 + 人物 + 下次问题 + 对话原文）
- 事件文件写入 `events/{life_stage}/`
- 人物文件写入 `people/{category}/`

**老用户回来（Restart）**：
- 加载上次 session archive 的摘要和对话记录
- 生成"欢迎回来"开场白（引用上次摘要 + 当前引导问题）
- 恢复 guided state（接着上次的问题继续）

### 3.3 知识库整理

**Agent**：`src/agents/kb_organizer_agent.py`
**Runner**：`src/service/agent_runners/kb_organizer_runner.py`

通过 `POST /api/kb-organizer/run` 触发。执行 8 个任务：
1. 设置索引
2. 读取所有记忆文件
3. 合并重复事件
4. 检测矛盾（如不同文件中提到的出生年份不同）
5. 处理矛盾（写入 `conflict.md`）
6. 修复文件间链接
7. 清理冗余
8. 最终化索引

### 3.4 故事生成

**Agent**：`src/agents/story_generation_agent.py`
**Runner**：`src/service/agent_runners/story_runner.py`

通过 `POST /api/stories/generate` 触发。

**流程**：
1. 扫描 `events/` 目录，找出未消费的事件文件
2. 按人生阶段分组（childhood / youth / middle_age / elderly）
3. 每个阶段独立判断生成门槛：首篇选最早 **3 个事件**，后续每篇选最早 **10 个事件**
4. LLM 生成第一人称叙事（JSON: title + body + image_prompt + illustration_prompts）
5. 保存为 `stories/{stage}_story_{timestamp}.md`
6. 生成封面图 + 四宫格插图（并行调用图片服务）
7. 按本篇实际使用数量标记事件为已消费（`.story_state.json`）

**图片生成约束**：
- 主人公性别从 `user.md` 读取，注入到 image prompt
- 明确指定 Chinese ethnicity
- 年龄跟随故事的人生阶段（不一定是老人——回忆年轻时就应该生成年轻人）

### 3.5 传记写作

**两步流程**：

**Step 1：大纲生成**
- **Agent**：`src/agents/biography_outline_agent.py`
- **Runner**：`src/service/agent_runners/outline_runner.py`
- 通过 `POST /api/biography/outline/generate` 触发
- 扫描所有素材（events / people / timeline / themes）
- 生成 `biography/outline.yaml`（章节列表，每章有 id / title / life_stage / source_materials / status）
- 章节状态机：`draft` → `confirmed` → `written` / `outdated`

**Step 2：逐章写作**
- **Agent**：`src/agents/biography_writing_agent.py`
- **Runner**：`src/service/agent_runners/writing_runner.py`
- 通过 `POST /api/biography/writing/run` 触发
- 对每个 `status=confirmed` 的章节：
  1. 收集源素材（事件文件、人物档案、时间线上下文）
  2. LLM 生成章节（`biography_chapter_writer` prompt）
  3. LLM 自审（`biography_chapter_reviewer` prompt，打分 + 修订建议）
  4. 分数低于阈值 → 应用修订
  5. 保存为 `biography/chapters/ch{NN}_{title}.md`
  6. 标记为 `written`
- 最终合并所有章节为 `biography/full_biography.md`

**增量更新**：新增事件 → 重新生成大纲 → 新章节标记 `draft`，受影响的已有章节标记 `outdated` → 确认后重新写作

### 3.6 API 路由一览

| Route 文件 | 端点 | 通信方式 |
|-----------|------|---------|
| `src/service/routes/interview.py` | `/api/interview/profile/prefill` | JSON |
| | `/api/interview/start` | SSE |
| | `/api/interview/message` | SSE |
| | `/api/interview/end` | JSON |
| | `/api/interview/status/{user_id}/{session_id}` | JSON |
| `src/service/routes/kb_organizer.py` | `/api/kb-organizer/run` | SSE |
| | `/api/kb-organizer/result/{user_id}` | JSON |
| `src/service/routes/stories.py` | `/api/stories/generate` | SSE |
| | `/api/stories/{user_id}` | JSON |
| | `/api/stories/{user_id}/{story_id}` | JSON |
| `src/service/routes/biography_outline.py` | `/api/biography/outline/generate` | SSE |
| | `/api/biography/outline/{user_id}` | JSON |
| | `PUT .../chapters/{chapter_id}/confirm` | JSON |
| `src/service/routes/biography_writing.py` | `/api/biography/writing/run` | SSE |
| | `/api/biography/writing/{user_id}/chapters` | JSON |
| | `/api/biography/writing/{user_id}/full` | JSON |
| `src/service/routes/files.py` | `/api/files/{user_id}/{path}` | JSON/Binary |
| `src/service/routes/users.py` | `DELETE /api/users/{user_id}` | JSON |

**SSE 事件类型**（常见的）：
`task_started` → `scanning` → `generating` → `saved` → `completed` / `failed` → `done`

---

## 四、知识库文件结构

每个用户的目录在 `knowledge_base/{user_id}/`：

```
{user_id}/
├── user.md                           # 用户画像（姓名、年龄、性别、职业…）
├── index.md                          # KB 索引
├── summary_index.md                  # 摘要索引
├── guided_initial_state.json         # 引导式采访进度（当前问题、已完成问题、追问次数）
│
├── events/                           # 人生事件（按阶段分目录）
│   ├── childhood/                    # 童年时期
│   ├── youth/                        # 青年时期
│   ├── middle_age/                   # 中年时期
│   └── elderly/                      # 老年时期
│
├── people/                           # 人物档案
│   ├── family/                       # 家人
│   ├── friends/                      # 朋友
│   ├── colleagues/                   # 同事
│   └── others/                       # 其他
│
├── timeline/                         # 时间线
├── themes/                           # 主题聚类
├── sessions/                         # 采访归档（session_YYYYMMDD_HHMMSS.md）
│
├── stories/                          # 生成的故事
│   ├── .story_state.json             # 事件消费状态追踪
│   ├── {stage}_story_*.md            # 故事正文
│   ├── {stage}_story_*_cover.png     # 封面图
│   └── {stage}_story_*_illust.png    # 四宫格插图
│
├── biography/                        # 生成的传记
│   ├── outline.yaml                  # 大纲（章节列表 + 状态）
│   ├── chapters/                     # 各章节文件
│   │   └── ch{NN}_{title}.md
│   └── full_biography.md             # 合并后的完整传记
│
└── conflict.md                       # 矛盾记录（如不同来源的年份冲突）
```

---

## 五、Prompt 模板

### `Prompts/` 目录（Markdown 格式的 Agent Prompt）

| 文件 | 用途 |
|------|------|
| `ProfileCollection-Prompt.md` | 用户画像采集 |
| `QuestionGenerator-Prompt.md` | 自由采访问题生成 |
| `KnowledgeBaseQuerier-Prompt.md` | KB 查询策略 |
| `MemoryOrganizer-Prompt.md` | 记忆整理为事件/人物/时间线 |
| `ContentSummarizer-Prompt.md` | 对话摘要 |
| `EmotionDetector-Prompt.md` | 情绪检测 |
| `SessionEndGuide-Prompt.md` | 会话结束引导 + 归档 |

### `src/prompts/` 目录（代码中使用的模板）

| 文件 | 用途 |
|------|------|
| `BiographyChapterWriter-Prompt.md` | 传记章节写作 |
| `BiographyChapterReviewer-Prompt.md` | 传记章节审稿 |
| 其他 Python 模块中的内联 prompt | 如 `guided_initial_interview_controller.py` 中的决策 prompt |

---

## 六、Langfuse 可观测性

### 6.1 入口文件

`src/services/observability.py` — 基于 Langfuse SDK 的薄封装层。

### 6.2 核心概念

```
ObservabilityContext (请求级)
├── trace_id: UUID — 一个 API 请求对应一个 trace
├── agent: str — "interview" / "biography_writing" / "story_generation" 等
├── operation: str — "start" / "message" / "run" 等
├── user_id / session_id / phase
└── tags / metadata
    │
    ├── Span (操作级) — observe_step()
    │   ├── name: "turn.identify_key_information" / "story_generation.generate" 等
    │   ├── as_type: "tool" / "span"
    │   └── input / output / metadata
    │
    └── Observation (LLM 调用级)
        └── 自动通过 llm_service.build_langchain_config() 注入
```

### 6.3 使用模式

**1) API 路由级别**：
```python
api_observation = start_api_observation(
    agent="interview",
    operation="start",
    route="POST /interview/start",
    user_id=request.user_id,
    input=request.model_dump(),
)
# ... 处理逻辑 ...
api_observation.end(status="completed", output={...})
```

**2) Agent / Service 步骤级别**：
```python
with observability_context(ctx.child(operation="generate")):
    with observe_step("story_generation.generate", as_type="tool",
                      input={"event_count": len(events)},
                      metadata={"attempt": 1, "life_stage": "childhood"}):
        result = await llm_service.invoke(...)
```

**3) LLM 调用自动集成**：
```python
# llm_service.invoke() 内部自动从 observability_context 读取当前 trace
# 构建 LangChain callback handler，注入 run_name / tags / metadata
result = await llm_service.invoke(
    prompt=prompt,
    trace_node="guided.generate_next",  # 在 Langfuse 中的节点名
)
```

### 6.4 追踪覆盖范围

| 模块 | 追踪内容 | trace_node 示例 |
|------|---------|----------------|
| Interview Agent | 关键信息提取、KB 查询、session end | `turn.identify_key_information`, `turn.kb_query`, `ending.generate_summary` |
| Guided Controller | 引导问题决策、问题推进 | `guided.generate_next`, `guided.advance_to_next_question` |
| Profile Agent | 信息提取、阶段决策 | `profile.extract_info`, `profile.decide_phase` |
| Story Agent | 事件扫描、故事生成（含重试）、图片生成 | `story_generation.generate`, `story_generation.generate_image` |
| Biography Outline | 素材扫描、分析、大纲生成 | `outline.scan_materials`, `outline.analyze`, `outline.generate` |
| Biography Writing | 素材收集、章节写作、审稿、合并 | `writing.gather_materials`, `writing.write_chapter`, `writing.merge_biography` |
| KB Organizer | 8 个任务节点 | `kb_organizer.task_{1-8}` |
| LLM Service | 每次 LLM 调用（含 template name、model、tokens） | 自动从调用方继承 |

### 6.5 环境变量

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com  # 或自部署地址
```

在 `app.py` 的 lifespan 中初始化，shutdown 时 flush。

---

## 七、关键文件索引

### 入口 & 配置
| 文件 | 职责 |
|------|------|
| `run_server.py` | 直接启动 uvicorn |
| `start_service.py` | 生产环境启动器（env 检查 + 依赖安装） |
| `src/service/app.py` | FastAPI 应用工厂（注册 7 个 router + lifespan） |
| `src/config/llm_config.py` | LLM 配置（model、API key、temperature） |
| `src/config/image_config.py` | 图片生成配置（model、size） |
| `src/config/initial_interview_questions.py` | 加载 62 个预设采访问题（从 CSV） |
| `src/config/profile_questions.py` | Profile 采集问题库 |

### Agents
| 文件 | 职责 |
|------|------|
| `src/agents/profile_collection_agent.py` | 用户画像采集 |
| `src/agents/interview_session_agent.py` | 采访会话编排（start/message/end） |
| `src/agents/interview_agent.py` | 采访对话引擎 |
| `src/agents/guided_initial_interview_controller.py` | 引导式采访控制器（64 题） |
| `src/agents/kb_organizer_agent.py` | 知识库整理（去重/合并/矛盾检测） |
| `src/agents/story_generation_agent.py` | 故事生成（15 事件 → 叙事 + 图） |
| `src/agents/biography_outline_agent.py` | 传记大纲生成 |
| `src/agents/biography_writing_agent.py` | 传记逐章写作 + 自审 |

### Agent Runners（SSE 桥接层）
| 文件 | 职责 |
|------|------|
| `src/service/agent_runners/base_runner.py` | Runner 基类（trace context 构建） |
| `src/service/agent_runners/interview_runner.py` | 采访 Runner |
| `src/service/agent_runners/kb_organizer_runner.py` | KB 整理 Runner |
| `src/service/agent_runners/story_runner.py` | 故事生成 Runner（含并行图片生成） |
| `src/service/agent_runners/outline_runner.py` | 大纲生成 Runner |
| `src/service/agent_runners/writing_runner.py` | 传记写作 Runner |

### Services
| 文件 | 职责 |
|------|------|
| `src/services/llm_service.py` | LLM 调用封装（重试 + Langfuse 集成） |
| `src/services/observability.py` | Langfuse 可观测层 |
| `src/services/question_generator.py` | 自由采访问题生成器 |
| `src/services/memory_manager.py` | 记忆提取/归档/查询 |
| `src/services/image_generation_service.py` | 图片生成服务 |
| `src/services/biography_file_manager.py` | 传记文件管理 |
| `src/services/biography_material_analyzer.py` | 素材分析器 |

### Storage
| 文件 | 职责 |
|------|------|
| `src/storage/markdown_file_manager.py` | Markdown 文件 CRUD（事件/人物/时间线/会话/传记） |
| `src/storage/memory_repository.py` | 记忆持久化 Repository |
| `src/storage/file_operations.py` | 底层文件 IO |

### Tests
| 文件 | 职责 |
|------|------|
| `tests/e2e/test_track_a_interview.py` | E2E: 采访 + 故事生成 |
| `tests/e2e/test_track_b_biography.py` | E2E: 传记生成管线 |
| `tests/integration/_common.py` | 集成测试工具（SSE 解析、服务管理） |
| `tests/integration/test_biography_outline_api.py` | 集成: 大纲 API |
| `tests/integration/test_biography_writing_api.py` | 集成: 写作 API |
| `tests/test_service/` | 单元测试（routes、session manager、SSE 等） |

### Documentation
| 文件 | 职责 |
|------|------|
| `API接口文档.md` | 完整 API 参考文档 |
| `README.md` | 项目概述 + 快速启动 |
| `问答引导层Agent-系统架构设计.md` | 采访引导层设计文档 |
| `传记写作Agent架构文档.md` | 传记写作 Agent 架构 |

---

## 八、已知问题 & 待办

### 传记写作质量问题（已分析，未修复）

1. **杜撰内容**：`BiographyChapterWriter-Prompt.md` 中有"可以合理补充感官细节"、"为重要人物加入对话"等指令，导致 LLM 编造素材中没有的内容
2. **章节过长且偏离标题**：字数上限 3000 太高，且缺少"一章一主题"约束
3. **语气问题**：缺少尊重约束，可能产出"可怜""不幸"等居高临下的表达

已有修复计划（重写 Writer + Reviewer prompt + 扩充 sanitize_text），但尚未实施。接手后可以在 plan 文件中查看方案。

### 其他注意事项

- 单元测试中 `test_resume_loads_context` 有一个已知的断言失败（assert "刘爷爷" 但得到 "您"），与近期工作无关
- `.env` 需要配置 DeepSeek API key（`DEEPSEEK_APIKEY`）才能运行 LLM 相关功能
- E2E 测试会自动启动/关闭后端服务，不需要手动启动
