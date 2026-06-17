# Agent 服务接口文档

## 一、概述

### 1.1 服务架构

本服务为"老人自传写作"系统的后端 API 层，负责将四个 AI Agent 和一个文件服务封装为标准 HTTP/SSE 接口，供前端 Web 应用调用。

**Agent 列表：**

| Agent | 类型 | 说明 |
|-------|------|------|
| 采访 Agent | 交互式 | 与用户进行多轮对话，收集人生故事素材 |
| 知识库整理 Agent | 任务式 | 自动整理、合并、去重知识库文件 |
| 传记大纲 Agent | 任务式 | 扫描知识库并生成传记章节大纲 |
| 传记写作 Agent | 任务式 | 根据大纲逐章写作生成传记全文 |

### 1.2 Base URL

```
http://{host}:{port}/api
```

### 1.3 认证方式

所有接口通过 `user_id` 字段标识用户身份。`user_id` 直接映射到服务端知识库路径：

```
knowledge_base/{user_id}/
```

当前版本不使用 Token 认证，`user_id` 通过请求体或路径参数传递。

### 1.4 SSE 流式协议说明

本系统大量使用 **Server-Sent Events (SSE)** 协议进行实时通信：

- **Content-Type**: `text/event-stream`
- **连接方式**: 客户端通过 POST/GET 请求建立长连接，服务端持续推送事件
- **事件格式**: 每个事件由 `event:` 和 `data:` 行组成，以空行分隔
- **心跳**: 服务端每 15 秒发送 `:keepalive` 注释行保持连接
- **结束标志**: 发送 `event: done` 事件表示流结束

```
event: <事件类型>
data: <JSON 数据>

```

---

## 二、通用约定

### 2.1 请求格式

- 请求体统一使用 `application/json`
- 字符编码: `UTF-8`
- 时间格式: ISO 8601 (`2026-05-16T10:30:00+08:00`)

### 2.2 SSE 事件通用格式

```
event: <event_type>
data: {"timestamp": "2026-05-16T10:30:00+08:00", ...payload}

```

所有 SSE 事件的 `data` 字段为合法 JSON，且必包含 `timestamp` 字段。

### 2.3 错误响应格式

**HTTP 错误（非 SSE）：**

```json
{
  "error": {
    "code": "USER_NOT_FOUND",
    "message": "用户 test_user003 的知识库不存在",
    "details": null
  }
}
```

**SSE 流中的错误事件：**

```
event: error
data: {"code": "AGENT_ERROR", "message": "LLM 服务调用失败", "recoverable": false}
```

### 2.4 通用错误码

| HTTP 状态码 | 错误码 | 说明 |
|-------------|--------|------|
| 400 | `INVALID_REQUEST` | 请求参数不合法 |
| 404 | `USER_NOT_FOUND` | 用户知识库不存在 |
| 409 | `TASK_ALREADY_RUNNING` | 该用户已有相同类型任务正在运行 |
| 500 | `INTERNAL_ERROR` | 服务内部错误 |
| 503 | `LLM_UNAVAILABLE` | LLM 服务不可用 |

### 2.5 user_id 约定

- 仅包含字母、数字、下划线
- 长度 3~50 字符
- 对应服务端目录: `knowledge_base/{user_id}/`

---

## 三、采访 Agent 接口（交互式）

采访 Agent 支持持续多轮对话，分为「用户信息收集」和「主体采访」两个阶段。主体采访内部会先执行一段初期受控采访，再进入自由发散采访。每次会话最长 15 分钟。

### 3.0 微信画像预填（启动前调用）

**POST** `/api/interview/profile/prefill`

在调用 `/api/interview/start` 之前，由微信侧或前端把已知用户画像写入服务端。用于避免语音识别错误姓名、年龄等基础信息。

`user_id` 必须由前端传入，并且后续 `/api/interview/start`、`/api/interview/message`、`/api/interview/end` 都必须使用同一个 `user_id`。服务端会把画像写入 `knowledge_base/{user_id}/user.md`，`wechat_id` 只作为微信侧映射同一人的外部标识保存。

**请求体：**

```json
{
  "wechat_id": "wx_openid_abc",
  "user_id": "test_user002",
  "name": "王秀兰",
  "age": 78,
  "birth_date": "1948-01-02",
  "gender": "女"
}
```

**字段说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `wechat_id` | string | 是 | 微信侧稳定标识，用于映射同一人 |
| `user_id` | string | 是 | 现有系统用户标识；决定写入的 `knowledge_base/{user_id}/` 文件夹 |
| `name` | string | 否 | 微信侧获取的姓名 |
| `age` | integer | 否 | 微信侧获取的年龄 |
| `birth_date` | string | 否 | 出生日期；服务端会从中提取出生年份 |
| `gender` | string | 否 | 性别，支持 `男/女/male/female` 等常见值 |

**响应：**

```json
{
  "status": "ok",
  "user_id": "test_user002",
  "wechat_id": "wx_openid_abc",
  "profile": {
    "wechat_id": "wx_openid_abc",
    "name": "王秀兰",
    "age": "78",
    "gender": "女",
    "birth_date": "1948-01-02",
    "birth_year": "1948"
  },
  "profile_complete": false,
  "missing_required_fields": [
    "occupation",
    "family_status",
    "living_arrangement"
  ]
}
```

预填接口只会写入已知字段。当前画像流程仍需要补齐：`occupation`、`family_status`、`living_arrangement`。这些字段补齐后，用户才会被视为已完成画像并直接进入主体采访。

### 3.0.1 初期受控采访

画像完成后，服务端会在主体采访内部先使用静态预设问题清单引导早期访谈。该流程不新增 API，也不会在正式响应里额外返回进度字段。

- 静态问题清单位于 `src/config/data/initial_interview_questions.csv`，服务启动时由 `src/config/initial_interview_questions.py` 读取；其中 `stage` 使用 `childhood`、`youth`、`middle_age`、`elderly` 等标准阶段名，`stage_label` 保留中文阶段名
- 进度状态保存到 `knowledge_base/{user_id}/guided_initial_state.json`
- 每个预设问题最多追问 10 次；AI 可自然过渡到下一个问题
- 如果用户主动提到强相关候选问题，仍会通过现有 `question_source=candidate_question` 和 `candidate_question_id` 返回给前端
- 预设问题全部完成后，采访自动切回自由发散模式

### 3.1 启动会话

**POST** `/api/interview/start`

启动一次新的采访会话。服务端创建 `InterviewSessionAgent` 实例，根据用户知识库状态决定进入信息收集或直接采访。

**幂等性：** 如果该用户已有一个活跃的采访会话（未调用 `/end`），重复调用本接口不会创建新的 Agent，而是复用已有会话，返回 `"reused": true`，原有对话历史和阶段状态保持不变。

**请求体：**

```json
{
  "user_id": "test_user002"
}
```

**响应：** SSE 流

**场景一：新建会话**

```
event: session_started
data: {"session_id": "sess_20260516_103000_abc123", "user_id": "test_user002", "phase": "profile", "reused": false, "timestamp": "2026-05-16T10:30:00+08:00"}

event: agent_message
data: {"session_id": "sess_20260516_103000_abc123", "message": "您好！我是您的传记采访助手。在开始之前，我想先了解一些您的基本信息。请问您怎么称呼？", "phase": "profile", "timestamp": "2026-05-16T10:30:01+08:00"}

event: done
data: {"message": "会话已建立", "timestamp": "2026-05-16T10:30:02+08:00"}
```

**场景二：复用已有会话（重复调用）**

```
event: session_started
data: {"session_id": "sess_20260516_103000_abc123", "user_id": "test_user002", "phase": "interview", "reused": true, "timestamp": "2026-05-16T10:32:00+08:00"}

event: agent_message
data: {"session_id": "sess_20260516_103000_abc123", "message": "当前会话已存在，我们继续吧！", "phase": "interview", "timestamp": "2026-05-16T10:32:01+08:00"}

event: done
data: {"message": "会话已建立", "timestamp": "2026-05-16T10:32:02+08:00"}
```

**`session_started` 字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 会话标识 |
| `user_id` | string | 用户标识 |
| `phase` | string | 当前会话阶段 |
| `reused` | boolean | `false` = 新建会话；`true` = 复用已有会话，Agent 未重建 |
| `timestamp` | string | 事件时间戳 |

**phase 枚举值：**

| 值 | 说明 |
|----|------|
| `profile` | 用户信息收集阶段 |
| `interview` | 主体采访阶段 |
| `ending` | 结束引导阶段 |

---

### 3.2 发送消息

**POST** `/api/interview/message`

用户在已有会话中发送一条消息，服务端将返回 Agent 的回复。

**请求体：**

```json
{
  "user_id": "test_user002",
  "session_id": "sess_20260516_103000_abc123",
  "message": "我叫张伟，今年78岁了。",
  "candidate_questions": [
    {"id": "q1", "question": "您当年为什么选择参军？"}
  ]
}
```

**字段说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_id` | string | 是 | 用户标识 |
| `session_id` | string | 是 | 会话标识（由 start 接口返回） |
| `message` | string | 是 | 用户消息内容 |
| `candidate_questions` | array | 否 | 家属提前准备的候选问题列表（仅 interview 阶段生效） |

`candidate_questions` 每项结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 问题唯一标识（前端用于回写云函数标记 asked） |
| `question` | string | 问题原文 |

**响应：** SSE 流

```
event: agent_message
data: {"session_id": "sess_20260516_103000_abc123", "message": "张伟老师您好！78岁，那您经历了很多时代变迁呢。请问您出生在哪里？", "phase": "profile", "question_source": "generated", "candidate_question_id": null, "timestamp": "2026-05-16T10:30:15+08:00"}

```

**`agent_message` 字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 会话标识 |
| `message` | string | Agent 回复内容 |
| `phase` | string | 当前阶段（profile / interview / ending） |
| `question_source` | string | 问题来源：`generated`（AI 生成）或 `candidate_question`（候选问题改写） |
| `candidate_question_id` | string \| null | 当 `question_source` 为 `candidate_question` 时，返回对应的候选问题 ID |
| `timestamp` | string | ISO 8601 时间戳 |

**使用候选问题示例：**

当老人回答与候选问题相关时，Agent 会选择并改写该问题：

```
event: agent_message
data: {"session_id": "sess_20260516_103000_abc123", "message": "您刚才提到在部队待了五年，当时是什么让您下定决心去参军的？", "phase": "interview", "question_source": "candidate_question", "candidate_question_id": "q1", "timestamp": "2026-05-16T10:31:00+08:00"}

```

前端收到 `question_source=candidate_question` 后，应回写云函数标记该候选问题为 `asked`：
```
PATCH /candidate-questions/{candidate_question_id}  status=asked
```

**说明：**
- 如果 Agent 检测到阶段转换（如从 profile 到 interview），会先发送阶段切换事件：

```
event: phase_changed
data: {"session_id": "sess_20260516_103000_abc123", "from_phase": "profile", "to_phase": "interview", "timestamp": "2026-05-16T10:31:00+08:00"}

event: agent_message
data: {"session_id": "sess_20260516_103000_abc123", "message": "好的，基本信息收集完毕。现在让我们开始聊聊您的人生故事吧...", "phase": "interview", "question_source": "generated", "candidate_question_id": null, "timestamp": "2026-05-16T10:31:01+08:00"}

```

---

### 3.3 结束会话

**POST** `/api/interview/end`

主动结束当前会话。服务端会保存对话历史并触发知识归档。

**请求体：**

```json
{
  "user_id": "test_user002",
  "session_id": "sess_20260516_103000_abc123"
}
```

**响应：** JSON

```json
{
  "status": "ended",
  "session_id": "sess_20260516_103000_abc123",
  "title": "童年青岛院子记忆",
  "summary": {
    "total_turns": 24,
    "phase_reached": "closed",
    "archived": true
  },
  "ending_message": "王奶奶，今天和您聊天真的很开心！在这段时间里，您跟我分享了很多珍贵的回忆...",
  "structured_archive": {
    "status": "success",
    "error": null
  }
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 固定值 `"ended"` |
| `session_id` | string | 会话标识 |
| `title` | string | 本次对话的简短标题（5-15字），由 LLM 根据对话内容生成，可用于会话列表展示 |
| `summary.total_turns` | integer | 本次会话总对话轮次 |
| `summary.phase_reached` | string | 会话结束时所处阶段 |
| `summary.archived` | boolean | 是否已完成归档 |
| `ending_message` | string | LLM 生成的结束引导消息（含内容回顾与下次话题预告） |
| `structured_archive` | object/null | 结构化归档结果，`status` 为 `"success"` / `"failed"` / `"pending"` |

---

### 3.4 获取会话状态

**GET** `/api/interview/status/{user_id}/{session_id}`

查询当前会话的实时状态。

**响应：**

```json
{
  "session_id": "sess_20260516_103000_abc123",
  "user_id": "test_user002",
  "phase": "interview",
  "turn_count": 12,
  "elapsed_minutes": 8,
  "remaining_minutes": 7,
  "current_topic": {
    "type": "event",
    "name": "上山下乡经历",
    "depth": 2
  },
  "emotion_state": {
    "emotion_type": "nostalgic",
    "intensity": "medium"
  }
}
```

---

## 四、知识库整理 Agent 接口（任务式）

知识库整理 Agent 自动执行文件去重合并、矛盾检测、链接修复等整理任务。

### 4.1 启动整理任务

**POST** `/api/kb-organizer/run`

**请求体：**

```json
{
  "user_id": "test_user002"
}
```

**响应：** SSE 流

完整的事件流示例：

```
event: task_started
data: {"user_id": "test_user002", "task_count": 7, "timestamp": "2026-05-16T11:00:00+08:00"}

event: task_progress
data: {"task_id": "task_001", "task_type": "setup_workspace", "status": "in_progress", "description": "初始化工作目录...", "timestamp": "2026-05-16T11:00:01+08:00"}

event: task_progress
data: {"task_id": "task_001", "task_type": "setup_workspace", "status": "completed", "description": "工作目录初始化完成", "timestamp": "2026-05-16T11:00:03+08:00"}

event: task_progress
data: {"task_id": "task_002", "task_type": "read_documents", "status": "in_progress", "description": "读取文档内容...", "timestamp": "2026-05-16T11:00:03+08:00"}

event: task_progress
data: {"task_id": "task_002", "task_type": "read_documents", "status": "completed", "description": "已读取 23 个文档", "timestamp": "2026-05-16T11:00:05+08:00"}

event: task_progress
data: {"task_id": "task_003", "task_type": "merge_duplicates", "status": "in_progress", "description": "正在合并重复文档...", "timestamp": "2026-05-16T11:00:05+08:00"}

event: task_progress
data: {"task_id": "task_003", "task_type": "merge_duplicates", "status": "completed", "description": "合并了 3 组重复文档", "timestamp": "2026-05-16T11:00:20+08:00"}

event: task_progress
data: {"task_id": "task_004", "task_type": "detect_contradictions", "status": "in_progress", "description": "检测矛盾信息...", "timestamp": "2026-05-16T11:00:20+08:00"}

event: task_progress
data: {"task_id": "task_004", "task_type": "detect_contradictions", "status": "completed", "description": "发现 2 处矛盾", "timestamp": "2026-05-16T11:00:35+08:00"}

event: task_progress
data: {"task_id": "task_005", "task_type": "repair_links", "status": "in_progress", "description": "修复文档链接...", "timestamp": "2026-05-16T11:00:35+08:00"}

event: task_progress
data: {"task_id": "task_005", "task_type": "repair_links", "status": "completed", "description": "修复了 5 个失效链接", "timestamp": "2026-05-16T11:00:40+08:00"}

event: task_progress
data: {"task_id": "task_006", "task_type": "prune_conversations", "status": "skipped", "description": "无需清理对话文件", "timestamp": "2026-05-16T11:00:40+08:00"}

event: task_progress
data: {"task_id": "task_007", "task_type": "finalize_swap", "status": "in_progress", "description": "原子替换知识库...", "timestamp": "2026-05-16T11:00:40+08:00"}

event: task_progress
data: {"task_id": "task_007", "task_type": "finalize_swap", "status": "completed", "description": "知识库已更新，备份已保存", "timestamp": "2026-05-16T11:00:42+08:00"}

event: task_completed
data: {"status": "completed", "iteration_count": 1, "summary": {"merge_records": [{"merge_id": "merge_001", "source_files": ["events/childhood/出生.md", "events/childhood/出生记录.md"], "target_file": "events/childhood/出生.md", "merge_reason": "内容重复", "preserved_details": ["出生地点", "出生日期", "家庭情况"]}], "conflict_items": [{"conflict_id": "conflict_001", "conflict_type": "time", "description": "出生年份在两份文档中不一致：1948 vs 1949", "source_files": ["events/childhood/出生.md", "timeline/timeline.md"], "resolved": false}], "link_redirect_map": {"events/childhood/出生记录.md": "events/childhood/出生.md"}}, "timestamp": "2026-05-16T11:00:42+08:00"}

event: done
data: {"message": "知识库整理完成"}

```

**task_type 枚举：**

| 值 | 说明 |
|----|------|
| `setup_workspace` | 初始化工作目录 |
| `read_documents` | 读取文档内容 |
| `merge_duplicates` | 合并重复文档 |
| `check_conflicts` | 检查冲突 |
| `detect_contradictions` | 检测矛盾信息 |
| `repair_links` | 修复链接 |
| `prune_conversations` | 清理对话文件 |
| `finalize_swap` | 最终替换 |

**task status 枚举：**

| 值 | 说明 |
|----|------|
| `pending` | 等待执行 |
| `in_progress` | 执行中 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `skipped` | 已跳过 |

---

### 4.2 获取最近整理结果

**GET** `/api/kb-organizer/result/{user_id}`

获取最近一次整理任务的结果摘要。

**响应：**

```json
{
  "user_id": "test_user002",
  "status": "completed",
  "completed_at": "2026-05-16T11:00:42+08:00",
  "iteration_count": 1,
  "merge_records": [
    {
      "merge_id": "merge_001",
      "source_files": ["events/childhood/出生.md", "events/childhood/出生记录.md"],
      "target_file": "events/childhood/出生.md",
      "merge_reason": "内容重复",
      "preserved_details": ["出生地点", "出生日期", "家庭情况"]
    }
  ],
  "conflict_items": [
    {
      "conflict_id": "conflict_001",
      "conflict_type": "time",
      "description": "出生年份在两份文档中不一致：1948 vs 1949",
      "source_files": ["events/childhood/出生.md", "timeline/timeline.md"],
      "resolved": false,
      "resolution": null
    }
  ],
  "link_redirect_map": {
    "events/childhood/出生记录.md": "events/childhood/出生.md"
  }
}
```

---

## 五、故事生成接口（任务式）

故事生成接口由前端触发。每次从用户知识库中选择最早的 15 个未消费事件生成一篇第一人称故事；故事生成并保存成功后，这 15 个事件会写入 `stories/.story_state.json`，下次不再计入数量。

### 5.1 获取故事列表

**GET** `/api/stories/{user_id}?life_stage=childhood`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_id` | string | 是 | 用户 ID |

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `life_stage` | string | 是 | 人生阶段：`childhood` / `youth` / `middle_age` / `elderly` |

**响应：**

```json
{
  "user_id": "test_user002",
  "life_stage": "childhood",
  "life_stage_label": "童年时期",
  "count": 1,
  "stories": [
    {
      "story_id": "childhood_story_20260605_100030",
      "story_path": "stories/childhood_story_20260605_100030.md",
      "title": "院子里的童年",
      "content": "# 院子里的童年\n\n> 生成时间：2026-06-05T10:00:30+08:00\n> 来源时期：童年时期\n> 来源事件数：15\n\n故事正文...\n\n<!--\nsource_events:\n- events/childhood/出生.md\n-->\n",
      "life_stage": "childhood",
      "life_stage_label": "童年时期",
      "created_at": "2026-06-05T10:00:30+08:00",
      "source_event_count": 15,
      "event_paths": ["events/childhood/出生.md"],
      "image_path": "stories/childhood_story_20260605_100030_cover.png",
      "size": 4096,
      "last_modified": "2026-06-05T02:00:30+00:00"
    }
  ]
}
```

**说明：**

- `content` 返回完整 Markdown 文件内容，包含标题、生成信息、故事正文和来源事件注释。
- `image_path` 为故事封面配图的相对路径，生成失败或未生成时为空字符串 `""`。图片文件保存在 `knowledge_base/{user_id}/stories/{story_id}_cover.png`。
- `life_stage` 只能取 `childhood`、`youth`、`middle_age`、`elderly`。
- 若对应时期还没有故事，返回 `count: 0` 和空数组。

### 5.2 生成故事

**POST** `/api/stories/generate`

**请求体：**

```json
{
  "user_id": "test_user002"
}
```

**响应：** SSE 流

```
event: task_started
data: {"user_id": "test_user002", "required_event_count": 15, "timestamp": "2026-06-05T10:00:00+08:00"}

event: scanning
data: {"step": "scanning", "message": "扫描到 18 个未生成故事的事件", "available_events": 18, "required_events": 15, "timestamp": "2026-06-05T10:00:01+08:00"}

event: generating
data: {"step": "generating", "message": "正在根据童年时期最早的 15 个事件生成故事...", "life_stage": "childhood", "life_stage_label": "童年时期", "selected_event_count": 15, "selected_event_paths": ["events/childhood/出生.md"], "timestamp": "2026-06-05T10:00:02+08:00"}

event: generating_image
data: {"step": "generating_image", "message": "正在为童年时期故事生成封面配图...", "story_id": "childhood_story_20260605_100030", "life_stage": "childhood", "life_stage_label": "童年时期", "timestamp": "2026-06-05T10:00:25+08:00"}

event: saved
data: {"step": "saved", "message": "故事已保存，事件消费状态已更新", "story_id": "childhood_story_20260605_100030", "story_path": "stories/childhood_story_20260605_100030.md", "life_stage": "childhood", "life_stage_label": "童年时期", "consumed_event_count": 15, "image_path": "stories/childhood_story_20260605_100030_cover.png", "timestamp": "2026-06-05T10:00:30+08:00"}

event: completed
data: {"status": "completed", "story_id": "childhood_story_20260605_100030", "story_path": "stories/childhood_story_20260605_100030.md", "life_stage": "childhood", "life_stage_label": "童年时期", "stories": [...], "failed_stages": [], "generated_story_count": 1, "consumed_event_count": 15, "remaining_event_count": 3, "timestamp": "2026-06-05T10:00:31+08:00"}

event: done
data: {"message": "故事生成完成"}
```

**事件不足 15 个：**

```
event: failed
data: {"status": "failed", "error_code": "INSUFFICIENT_EVENTS", "message": "未生成故事的事件不足15个", "available_events": 12, "required_events": 15, "timestamp": "2026-06-05T10:00:01+08:00"}

event: done
data: {"message": "任务失败"}
```

**说明：**

- 生成物保存到 `knowledge_base/{user_id}/stories/{life_stage}_story_YYYYMMDD_HHMMSS.md`。
- 故事正文不在 `completed` 事件中返回；前端可通过文件接口读取。
- 故事文本生成完成后，会自动调用通义万相（`wan2.7-image`）生成封面配图，保存为 `stories/{story_id}_cover.png`。
- `generating_image` 事件在配图生成开始时发出；若 `IMAGE_API_KEY` 未配置或 LLM 未返回 `image_prompt`，此事件不会出现。
- 配图生成失败时不影响故事保存，`saved` 事件中 `image_path` 为空字符串 `""`。
- `saved` 和 `completed` 事件中的 `image_path` 为封面图的相对路径（相对于用户知识库根目录）。
- 消费状态保存到 `stories/.story_state.json`，第一版仅按 `event_path` 判断是否已消费；事件被改名、移动或重写后会被视为新事件。
- 故事文件末尾会以注释形式保留来源事件路径，便于排查和溯源。
- 若故事文件已保存但状态索引保存失败，会返回 `STATE_SAVE_FAILED`，不发送 `completed`。

---

## 六、传记大纲 Agent 接口（任务式）

传记大纲 Agent 扫描知识库材料，自动生成或增量更新传记章节大纲。

### 6.1 生成/更新大纲

**POST** `/api/biography/outline/generate`

**请求体：**

```json
{
  "user_id": "test_user002"
}
```

**响应：** SSE 流

```
event: task_started
data: {"user_id": "test_user002", "mode": "generate", "timestamp": "2026-05-16T12:00:00+08:00"}

event: scanning
data: {"step": "scanning", "message": "正在扫描知识库材料...", "timestamp": "2026-05-16T12:00:01+08:00"}

event: scanning
data: {"step": "scanning", "message": "已扫描: 12 个事件, 8 个人物, 15 条时间线", "events_count": 12, "people_count": 8, "timeline_count": 15, "timestamp": "2026-05-16T12:00:05+08:00"}

event: analyzing
data: {"step": "analyzing", "message": "正在分析材料关联与主题...", "timestamp": "2026-05-16T12:00:05+08:00"}

event: analyzing
data: {"step": "analyzing", "message": "分析完成，识别到 5 个核心主题", "timestamp": "2026-05-16T12:00:15+08:00"}

event: generating
data: {"step": "generating", "message": "正在生成章节大纲...", "has_existing_outline": false, "timestamp": "2026-05-16T12:00:15+08:00"}

event: generating
data: {"step": "generating", "message": "生成了 6 个章节", "chapters_count": 6, "timestamp": "2026-05-16T12:00:30+08:00"}

event: completed
data: {"status": "completed", "outline": {"title": "我的人生故事", "author": "张伟", "style": "first_person_oral", "version": 1, "chapters": [{"id": "ch01", "title": "故乡的记忆", "life_stage": "childhood", "theme": "成长环境", "status": "draft", "source_materials": ["events/childhood/出生.md", "events/childhood/上学.md"], "summary": "描述童年时期的家庭环境和乡村生活..."}, {"id": "ch02", "title": "求学之路", "life_stage": "youth", "theme": "教育经历", "status": "draft", "source_materials": ["events/youth/高中.md", "events/youth/大学.md"], "summary": "讲述求学时期的努力和收获..."}]}, "changes_made": [{"action": "add", "chapter_id": "ch01", "reason": "基于童年事件材料新建"}, {"action": "add", "chapter_id": "ch02", "reason": "基于青年事件材料新建"}], "timestamp": "2026-05-16T12:00:31+08:00"}

event: done
data: {"message": "大纲生成完成"}

```

**增量模式**（知识库无变化时）：

```
event: task_started
data: {"user_id": "test_user002", "mode": "incremental", "timestamp": "2026-05-16T13:00:00+08:00"}

event: scanning
data: {"step": "scanning", "message": "正在扫描知识库材料...", "timestamp": "2026-05-16T13:00:01+08:00"}

event: completed
data: {"status": "completed", "has_changes": false, "message": "知识库无新增材料，大纲无需更新", "timestamp": "2026-05-16T13:00:03+08:00"}

event: done
data: {"message": "无需更新"}

```

---

### 6.2 获取当前大纲

**GET** `/api/biography/outline/{user_id}`

获取当前已保存的 outline.yaml 内容（JSON 格式返回）。

**响应：**

```json
{
  "title": "我的人生故事",
  "author": "张伟",
  "style": "first_person_oral",
  "version": 1,
  "last_updated": "2026-05-16T12:00:31+08:00",
  "chapters": [
    {
      "id": "ch01",
      "title": "故乡的记忆",
      "life_stage": "childhood",
      "theme": "成长环境",
      "status": "draft",
      "source_materials": [
        "events/childhood/出生.md",
        "events/childhood/上学.md"
      ],
      "summary": "描述童年时期的家庭环境和乡村生活，回忆父母的教诲和邻里间的温情。",
      "confirmed_at": null,
      "written_at": null
    },
    {
      "id": "ch02",
      "title": "求学之路",
      "life_stage": "youth",
      "theme": "教育经历",
      "status": "confirmed",
      "source_materials": [
        "events/youth/高中.md",
        "events/youth/大学.md"
      ],
      "summary": "讲述求学时期的努力和收获，以及对人生方向的思考。",
      "confirmed_at": "2026-05-16T13:00:00+08:00",
      "written_at": null
    }
  ]
}
```

---

### 6.3 确认章节

**PUT** `/api/biography/outline/{user_id}/chapters/{chapter_id}/confirm`

将指定章节的状态从 `draft` 变为 `confirmed`，表示用户确认该章节可以写作。

**请求体：**（可选）

```json
{
  "notes": "这个章节的方向很好，可以动笔了"
}
```

**响应：**

```json
{
  "chapter_id": "ch01",
  "status": "confirmed",
  "confirmed_at": "2026-05-16T14:00:00+08:00",
  "message": "章节已确认，可进行写作"
}
```

**错误场景：**

```json
{
  "error": {
    "code": "INVALID_STATUS_TRANSITION",
    "message": "章节 ch01 当前状态为 written，无法确认"
  }
}
```

---

### 6.4 章节状态枚举

| 值 | 说明 | 可转换至 |
|----|------|----------|
| `draft` | 新生成，待用户确认 | `confirmed` |
| `confirmed` | 用户已确认，待写作 | `written` |
| `written` | 已完成写作 | `outdated` |
| `outdated` | 源材料变更，需重新处理 | `draft` |

---

## 七、传记写作 Agent 接口（任务式）

传记写作 Agent 根据已确认的大纲章节逐章写作，并合并为完整传记。

### 7.1 启动写作任务

**POST** `/api/biography/writing/run`

**请求体：**

```json
{
  "user_id": "test_user002"
}
```

**前提条件：**
- 已生成 outline.yaml
- 至少有一个章节状态为 `confirmed`

**响应：** SSE 流

```
event: task_started
data: {"user_id": "test_user002", "chapters_to_write": 3, "timestamp": "2026-05-16T15:00:00+08:00"}

event: loading_tasks
data: {"step": "loading_tasks", "message": "正在加载写作任务...", "chapters": ["ch01", "ch02", "ch03"], "timestamp": "2026-05-16T15:00:01+08:00"}

event: writing_chapter
data: {"step": "writing_chapter", "chapter_id": "ch01", "chapter_title": "故乡的记忆", "status": "gathering_materials", "message": "正在收集章节素材...", "progress": "1/3", "timestamp": "2026-05-16T15:00:02+08:00"}

event: writing_chapter
data: {"step": "writing_chapter", "chapter_id": "ch01", "chapter_title": "故乡的记忆", "status": "writing", "message": "正在撰写初稿...", "progress": "1/3", "timestamp": "2026-05-16T15:00:10+08:00"}

event: reviewing
data: {"step": "reviewing", "chapter_id": "ch01", "chapter_title": "故乡的记忆", "message": "正在审阅润色...", "progress": "1/3", "timestamp": "2026-05-16T15:01:00+08:00"}

event: saved
data: {"step": "saved", "chapter_id": "ch01", "chapter_title": "故乡的记忆", "file_path": "biography/chapters/ch01_故乡的记忆.md", "word_count": 2350, "progress": "1/3", "timestamp": "2026-05-16T15:01:30+08:00"}

event: writing_chapter
data: {"step": "writing_chapter", "chapter_id": "ch02", "chapter_title": "求学之路", "status": "gathering_materials", "message": "正在收集章节素材...", "progress": "2/3", "timestamp": "2026-05-16T15:01:31+08:00"}

event: writing_chapter
data: {"step": "writing_chapter", "chapter_id": "ch02", "chapter_title": "求学之路", "status": "writing", "message": "正在撰写初稿...", "progress": "2/3", "timestamp": "2026-05-16T15:01:40+08:00"}

event: reviewing
data: {"step": "reviewing", "chapter_id": "ch02", "chapter_title": "求学之路", "message": "正在审阅润色...", "progress": "2/3", "timestamp": "2026-05-16T15:02:30+08:00"}

event: saved
data: {"step": "saved", "chapter_id": "ch02", "chapter_title": "求学之路", "file_path": "biography/chapters/ch02_求学之路.md", "word_count": 2100, "progress": "2/3", "timestamp": "2026-05-16T15:03:00+08:00"}

event: writing_chapter
data: {"step": "writing_chapter", "chapter_id": "ch03", "chapter_title": "工作岁月", "status": "writing", "message": "正在撰写初稿...", "progress": "3/3", "timestamp": "2026-05-16T15:03:01+08:00"}

event: reviewing
data: {"step": "reviewing", "chapter_id": "ch03", "chapter_title": "工作岁月", "message": "正在审阅润色...", "progress": "3/3", "timestamp": "2026-05-16T15:04:00+08:00"}

event: saved
data: {"step": "saved", "chapter_id": "ch03", "chapter_title": "工作岁月", "file_path": "biography/chapters/ch03_工作岁月.md", "word_count": 1980, "progress": "3/3", "timestamp": "2026-05-16T15:04:30+08:00"}

event: merging
data: {"step": "merging", "message": "正在合并为完整传记...", "timestamp": "2026-05-16T15:04:31+08:00"}

event: completed
data: {"status": "completed", "completed_chapters": ["ch01", "ch02", "ch03"], "total_word_count": 6430, "full_biography_path": "biography/full_biography.md", "timestamp": "2026-05-16T15:04:33+08:00"}

event: done
data: {"message": "传记写作完成"}

```

---

### 7.2 获取章节列表

**GET** `/api/biography/writing/{user_id}/chapters`

列出所有已写作完成的章节文件。

**响应：**

```json
{
  "user_id": "test_user002",
  "chapters": [
    {
      "chapter_id": "ch01",
      "title": "故乡的记忆",
      "file_path": "biography/chapters/ch01_故乡的记忆.md",
      "word_count": 2350,
      "written_at": "2026-05-16T15:01:30+08:00"
    },
    {
      "chapter_id": "ch02",
      "title": "求学之路",
      "file_path": "biography/chapters/ch02_求学之路.md",
      "word_count": 2100,
      "written_at": "2026-05-16T15:03:00+08:00"
    },
    {
      "chapter_id": "ch03",
      "title": "工作岁月",
      "file_path": "biography/chapters/ch03_工作岁月.md",
      "word_count": 1980,
      "written_at": "2026-05-16T15:04:30+08:00"
    }
  ],
  "total_word_count": 6430
}
```

---

### 7.3 获取完整传记

**GET** `/api/biography/writing/{user_id}/full`

获取合并后的完整传记内容。

**响应：**

```json
{
  "user_id": "test_user002",
  "title": "我的人生故事",
  "author": "张伟",
  "total_word_count": 6430,
  "chapters_count": 3,
  "generated_at": "2026-05-16T15:04:33+08:00",
  "content": "# 我的人生故事\n\n## 第一章 故乡的记忆\n\n我出生在一个小山村里...\n\n## 第二章 求学之路\n\n那年秋天，我背着母亲缝制的布书包...\n\n## 第三章 工作岁月\n\n大学毕业后，我被分配到..."
}
```

---

## 八、文件服务接口

文件服务提供对用户知识库目录的只读访问，支持浏览目录结构和读取文件内容。

### 8.1 列出文件目录

**GET** `/api/files/{user_id}`

列出指定用户知识库根目录下的文件和目录（仅一级）。

**响应：**

```json
{
  "user_id": "test_user002",
  "base_path": "knowledge_base/test_user002/",
  "items": [
    {"name": "events", "path": "events/", "type": "directory"},
    {"name": "people", "path": "people/", "type": "directory"},
    {"name": "timeline", "path": "timeline/", "type": "directory"},
    {"name": "themes", "path": "themes/", "type": "directory"},
    {"name": "biography", "path": "biography/", "type": "directory"},
    {"name": "index.md", "path": "index.md", "type": "file", "size": 234, "last_modified": "2026-05-16T10:00:00+08:00"},
    {"name": "conversation_2026-04-26_14-34-15.json", "path": "conversation_2026-04-26_14-34-15.json", "type": "file", "size": 15632, "last_modified": "2026-04-26T14:34:15+08:00"}
  ]
}
```

---

### 8.2 获取文件内容

**GET** `/api/files/{user_id}/{path}`

按相对路径获取文件内容。`{path}` 为相对于 `knowledge_base/{user_id}/` 的路径。

**示例请求：**

```
GET /api/files/test_user002/events/childhood/出生.md
```

**响应：**

```json
{
  "user_id": "test_user002",
  "filename": "出生.md",
  "path": "events/childhood/出生.md",
  "size": 456,
  "last_modified": "2026-05-13T22:45:44+08:00",
  "content_type": "text/markdown",
  "content": "# 出生\n\n## 基本信息\n- 时间：1948年农历三月\n- 地点：湖南省长沙市望城区\n\n## 详细描述\n我出生在一个普通的农民家庭..."
}
```

**如果请求路径为目录，返回该目录下的条目：**

```
GET /api/files/test_user002/events/childhood/
```

```json
{
  "user_id": "test_user002",
  "path": "events/childhood/",
  "type": "directory",
  "items": [
    {"name": "出生.md", "path": "events/childhood/出生.md", "type": "file", "size": 456, "last_modified": "2026-05-13T22:45:44+08:00"},
    {"name": "上学.md", "path": "events/childhood/上学.md", "type": "file", "size": 789, "last_modified": "2026-05-13T22:45:44+08:00"}
  ]
}
```

---

### 8.3 获取完整目录树

**GET** `/api/files/{user_id}/tree`

递归获取用户知识库的完整目录树结构。

**响应：**

```json
{
  "user_id": "test_user002",
  "tree": {
    "name": "test_user002",
    "type": "directory",
    "children": [
      {
        "name": "events",
        "type": "directory",
        "children": [
          {
            "name": "childhood",
            "type": "directory",
            "children": [
              {"name": "出生.md", "type": "file", "size": 456, "path": "events/childhood/出生.md"},
              {"name": "上学.md", "type": "file", "size": 789, "path": "events/childhood/上学.md"}
            ]
          },
          {
            "name": "youth",
            "type": "directory",
            "children": [
              {"name": "高中.md", "type": "file", "size": 1234, "path": "events/youth/高中.md"},
              {"name": "大学.md", "type": "file", "size": 2345, "path": "events/youth/大学.md"}
            ]
          },
          {
            "name": "middle_age",
            "type": "directory",
            "children": []
          },
          {
            "name": "elderly",
            "type": "directory",
            "children": []
          }
        ]
      },
      {
        "name": "people",
        "type": "directory",
        "children": [
          {
            "name": "family",
            "type": "directory",
            "children": [
              {"name": "父亲.md", "type": "file", "size": 567, "path": "people/family/父亲.md"}
            ]
          }
        ]
      },
      {
        "name": "timeline",
        "type": "directory",
        "children": [
          {"name": "timeline.md", "type": "file", "size": 3456, "path": "timeline/timeline.md"}
        ]
      },
      {
        "name": "biography",
        "type": "directory",
        "children": [
          {"name": "outline.yaml", "type": "file", "size": 2100, "path": "biography/outline.yaml"},
          {
            "name": "chapters",
            "type": "directory",
            "children": [
              {"name": "ch01_故乡的记忆.md", "type": "file", "size": 4700, "path": "biography/chapters/ch01_故乡的记忆.md"}
            ]
          },
          {"name": "full_biography.md", "type": "file", "size": 12860, "path": "biography/full_biography.md"}
        ]
      },
      {
        "name": "index.md",
        "type": "file",
        "size": 234,
        "path": "index.md"
      }
    ]
  }
}
```

---

## 九、SSE 事件格式规范

### 9.1 任务式 Agent 通用事件类型

| 事件类型 | 说明 | 触发时机 |
|----------|------|----------|
| `task_started` | 任务开始 | 任务启动时，包含任务总数 |
| `task_progress` | 任务进度更新 | 每个子任务状态变化时 |
| `scanning` | 扫描阶段 | 大纲 Agent 扫描知识库时 |
| `analyzing` | 分析阶段 | 大纲 Agent 分析材料时 |
| `generating` | 生成阶段 | 大纲 Agent 生成章节时 |
| `loading_tasks` | 加载任务 | 写作 Agent 加载写作队列时 |
| `writing_chapter` | 写作进度 | 写作 Agent 撰写每章时 |
| `reviewing` | 审阅阶段 | 写作 Agent 审阅润色时 |
| `saved` | 保存完成 | 单章写作保存时 |
| `merging` | 合并阶段 | 写作 Agent 合并全文时 |
| `completed` | 任务完成 | 全部任务成功完成 |
| `failed` | 任务失败 | 任务执行失败 |
| `error` | 错误 | 运行时出错 |
| `done` | 流结束 | SSE 连接即将关闭 |

### 9.2 交互式 Agent 事件类型

| 事件类型 | 说明 | 触发时机 |
|----------|------|----------|
| `session_started` | 会话已创建 | 调用 start 接口时 |
| `agent_message` | Agent 回复 | Agent 生成回复时 |
| `phase_changed` | 阶段切换 | profile→interview→ending |
| `session_ended` | 会话结束 | 会话正常结束时 |
| `error` | 错误 | 运行时出错 |

### 9.3 事件详细格式示例

#### task_started

```
event: task_started
data: {"user_id": "test_user002", "task_count": 7, "timestamp": "2026-05-16T11:00:00+08:00"}
```

#### task_progress

```
event: task_progress
data: {"task_id": "task_003", "task_type": "merge_duplicates", "status": "in_progress", "description": "正在合并重复文档...", "timestamp": "2026-05-16T11:00:05+08:00"}
```

#### task_completed

```
event: task_completed
data: {"status": "completed", "summary": {"merge_records": [...], "conflict_items": [...], "link_redirect_map": {...}}, "timestamp": "2026-05-16T11:00:42+08:00"}
```

#### task_failed

```
event: failed
data: {"status": "failed", "error_code": "LLM_TIMEOUT", "message": "LLM 调用超时，请稍后重试", "failed_task": {"task_id": "task_003", "task_type": "merge_duplicates"}, "timestamp": "2026-05-16T11:00:35+08:00"}
```

#### agent_message

```
event: agent_message
data: {"session_id": "sess_20260516_103000_abc123", "message": "您好！我是您的传记采访助手。在开始之前，我想先了解一些您的基本信息。请问您怎么称呼？", "phase": "profile", "turn_count": 1, "timestamp": "2026-05-16T10:30:01+08:00"}
```

#### session_ended

```
event: session_ended
data: {"session_id": "sess_20260516_103000_abc123", "conversation_saved": "knowledge_base/test_user002/conversation_2026-05-16_10-42-00.json", "total_turns": 24, "timestamp": "2026-05-16T10:42:00+08:00"}
```

#### done（流结束标志）

```
event: done
data: {"message": "流结束"}
```

### 9.4 前端 SSE 连接示例

```javascript
// 任务式 Agent 调用示例
const eventSource = new EventSource('/api/kb-organizer/run', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ user_id: 'test_user002' })
});

// 使用 fetch + ReadableStream（推荐，支持 POST）
async function runTaskAgent(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop(); // 保留不完整的行

    let eventType = '';
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7);
      } else if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        handleEvent(eventType, data);
      }
    }
  }
}

function handleEvent(eventType, data) {
  switch (eventType) {
    case 'task_started':
      console.log(`任务开始，共 ${data.task_count} 个子任务`);
      break;
    case 'task_progress':
      console.log(`[${data.task_id}] ${data.description}`);
      break;
    case 'task_completed':
      console.log('任务完成！', data.summary);
      break;
    case 'done':
      console.log('流结束');
      break;
  }
}
```

---

## 十、数据模型

### 10.1 OutlineDocument（大纲文档）

```json
{
  "title": "string - 传记标题",
  "author": "string - 传主姓名",
  "style": "string - 写作风格 (first_person_oral)",
  "version": "integer - 大纲版本号",
  "last_updated": "datetime - 最后更新时间",
  "chapters": "ChapterEntry[] - 章节列表"
}
```

### 10.2 ChapterEntry（章节条目）

```json
{
  "id": "string - 章节唯一标识 (ch01, ch02...)",
  "title": "string - 章节标题",
  "life_stage": "string - 人生阶段 (childhood|youth|middle_age|elderly)",
  "theme": "string - 章节主题",
  "status": "string - 章节状态 (draft|confirmed|written|outdated)",
  "source_materials": "string[] - 引用的知识库文件路径列表",
  "summary": "string - 章节内容摘要",
  "confirmed_at": "datetime|null - 确认时间",
  "written_at": "datetime|null - 写作完成时间"
}
```

### 10.3 OrganizerTask（整理任务）

```json
{
  "task_id": "string - 任务唯一标识",
  "task_type": "string - 任务类型",
  "description": "string - 任务描述",
  "status": "string - 任务状态 (pending|in_progress|completed|failed|skipped)",
  "result": "string|null - 执行结果摘要",
  "error": "string|null - 错误信息",
  "affected_files": "string[] - 受影响的文件列表",
  "retry_count": "integer - 重试次数"
}
```

### 10.4 MergeRecord（合并记录）

```json
{
  "merge_id": "string - 合并记录唯一标识",
  "source_files": "string[] - 被合并的源文件列表",
  "target_file": "string - 合并后的目标文件",
  "merge_reason": "string - 合并原因",
  "preserved_details": "string[] - 保留的关键细节清单"
}
```

### 10.5 ConflictItem（矛盾问题）

```json
{
  "conflict_id": "string - 矛盾唯一标识",
  "conflict_type": "string - 矛盾类型 (time|location|relationship|causal)",
  "description": "string - 矛盾描述",
  "source_files": "string[] - 涉及的文档路径",
  "resolved": "boolean - 是否已解决",
  "resolution": "string|null - 解决方案描述",
  "evidence": "string|null - 支撑解决的证据来源"
}
```

### 10.6 SessionState（采访会话状态）

```json
{
  "session_id": "string - 会话唯一标识",
  "created_at": "datetime - 创建时间",
  "last_activity": "datetime - 最后活动时间",
  "current_state": "string - 当前对话状态 (init|greeting|chatting|deep_dive|summarizing)",
  "current_phase": "string - 当前人生阶段 (childhood|youth|young_adult|middle_age|elderly)",
  "strategy": "string - 采访策略",
  "turn_count": "integer - 对话轮数",
  "coverage": "object - 各阶段覆盖率 {phase: float}",
  "collected_events": "string[] - 已收集事件ID列表",
  "collected_people": "string[] - 已收集人物ID列表",
  "current_topic": "TopicInfo|null - 当前话题",
  "emotion_state": "EmotionState - 情绪状态"
}
```

### 10.7 OutlineChange（大纲变更记录）

```json
{
  "action": "string - 变更动作 (add|update|mark_outdated)",
  "chapter_id": "string - 章节ID",
  "chapter_entry": "ChapterEntry|null - 新章节条目（add时）",
  "reason": "string - 变更原因"
}
```

### 10.8 ChapterTask（写作任务项）

```json
{
  "chapter_id": "string - 章节ID",
  "chapter_title": "string - 章节标题",
  "life_stage": "string - 人生阶段",
  "theme": "string - 章节主题",
  "source_materials": "string[] - 参考材料路径列表",
  "summary": "string - 章节摘要"
}
```

---

## 附录 A：接口总览

| 方法 | 路径 | 类型 | 说明 |
|------|------|------|------|
| POST | `/api/interview/start` | SSE | 启动采访会话 |
| POST | `/api/interview/message` | SSE | 发送用户消息 |
| POST | `/api/interview/end` | JSON | 结束会话 |
| GET | `/api/interview/status/{user_id}/{session_id}` | JSON | 获取会话状态 |
| POST | `/api/kb-organizer/run` | SSE | 启动知识库整理 |
| GET | `/api/kb-organizer/result/{user_id}` | JSON | 获取整理结果 |
| POST | `/api/stories/generate` | SSE | 生成一篇故事并消费 15 个事件 |
| POST | `/api/biography/outline/generate` | SSE | 生成/更新大纲 |
| GET | `/api/biography/outline/{user_id}` | JSON | 获取当前大纲 |
| PUT | `/api/biography/outline/{user_id}/chapters/{chapter_id}/confirm` | JSON | 确认章节 |
| POST | `/api/biography/writing/run` | SSE | 启动传记写作 |
| GET | `/api/biography/writing/{user_id}/chapters` | JSON | 获取章节列表 |
| GET | `/api/biography/writing/{user_id}/full` | JSON | 获取完整传记 |
| GET | `/api/files/{user_id}` | JSON | 列出文件目录 |
| GET | `/api/files/{user_id}/{path}` | JSON | 获取文件内容 |
| GET | `/api/files/{user_id}/tree` | JSON | 获取完整目录树 |
