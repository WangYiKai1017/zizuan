---
name: langfuse-trace-analyzer
description: 拉取并分析单个 Langfuse trace，定位一次具体 Agent/API 调用与业务期望不一致的地方。Use when the user provides a Langfuse trace id, asks to inspect/debug/analyze a trace, compare trace behavior with expected interview/profile/guided/story/biography flow, or says to pull a Langfuse trace locally. If no trace id is provided, ask the user for one before running the analysis.
---

# Langfuse Trace Analyzer

用于本地拉取一个具体 Langfuse trace，并基于当前项目业务规则做偏差分析。不要做全量数据集分析；每次只分析一个 trace。

## 工作流

1. **确认 trace id**
   - 如果用户没有给 trace id，先停下来询问。
   - 如果用户给了 trace id，直接继续，不要再确认。

2. **拉取 trace**
   - 从项目根目录运行：

```bash
./.venv/bin/python .ai/skills/langfuse-trace-analyzer/scripts/fetch_trace.py <trace_id>
```

   - 脚本会读取项目 `.env` 或当前 shell 环境中的：
     - `LANGFUSE_BASE_URL`
     - `LANGFUSE_PUBLIC_KEY`
     - `LANGFUSE_SECRET_KEY`
   - 不要在回复中打印、复制或总结密钥。
   - 默认输出到 `.ai/runs/langfuse-traces/<trace_id>/`：
     - `raw_observations.json`：原始 observation 数据
     - `timeline.md`：按时间排序的节点输入输出摘要
     - `analysis.md`：自动信号和业务核对底稿

3. **读取分析材料**
   - 先读 `analysis.md` 获取自动风险信号和业务核对清单。
   - 再读 `timeline.md` 还原实际执行路径。
   - 必要时用 `rg` 或结构化解析查看 `raw_observations.json` 中的完整 `input`、`output`、`metadata`。

4. **输出诊断**
   - 先列事实，再列偏差。
   - 每个问题按这个结构写：
     - 事实：trace 中发生了什么。
     - 期望：按业务规则应该怎样。
     - 偏差：哪里不一致。
     - 影响：会造成什么用户/业务问题。
     - 建议：下一步怎么改或怎么验证。
   - 如果 trace 拉取失败，先判断是环境变量缺失、Langfuse API 失败、时间窗口太窄，还是 trace 不属于当前项目；给出可执行的下一步。

## 当前项目业务期望

分析时优先核对这些约束：

- 新用户流程：画像字段必须先完成或预填；正式采访 start 后必须能对应同一个 `user_id` 文件夹。
- 微信画像预填：`wechat_id`、姓名、年龄、出生日期、性别应在 start 前写入；语音识别不应覆盖成错误姓名。
- 初期受控采访：画像完成后进入主体采访时，应优先推进静态预设问题；每个预设问题最多追问 1 次；允许短暂接住强情绪或自然使用相关候选问题。
- 候选问题：如果用了候选问题，响应应保留 `question_source=candidate_question` 和 `candidate_question_id`，前端才能标记已消费。
- 状态持久化：受控采访进度应写入当前用户知识库下的 `guided_initial_state.json`；缺失或损坏时应可重建。
- 故事生成：未消费 event 不足 15 个应失败；够 15 个时只消费最早 15 个；故事文件保存成功后才更新 `stories/.story_state.json`；一次触发只生成一篇故事。
- 传记/故事边界：故事生成不应走传记 outline/writing 流程；传记写作不应改写 story 状态。
- 观测完整性：trace metadata 应能关联 `agent`、`operation`、`user_id`、`session_id`、`node`；异常不应只存在日志里而没有 trace 信号。

## 常用命令

扩大查询窗口：

```bash
./.venv/bin/python .ai/skills/langfuse-trace-analyzer/scripts/fetch_trace.py <trace_id> --days 90
```

指定输出目录：

```bash
./.venv/bin/python .ai/skills/langfuse-trace-analyzer/scripts/fetch_trace.py <trace_id> --out-dir /tmp/langfuse-trace
```

快速查看节点名：

```bash
rg -n '^## ' .ai/runs/langfuse-traces/<trace_id>/timeline.md
```

查看完整 observation 的关键字段：

```bash
./.venv/bin/python - <<'PY'
import json
from pathlib import Path
p = Path(".ai/runs/langfuse-traces/<trace_id>/raw_observations.json")
data = json.loads(p.read_text())
for row in data["observations"]:
    print(row.get("startTime"), row.get("type"), row.get("name"), row.get("level"), row.get("statusMessage"))
PY
```

## 注意事项

- 只分析用户指定的单个 trace，不主动跑批量分析。
- 不要把 raw trace 全文粘贴给用户；只提炼与业务偏差有关的证据。
- 如果 observation 很少，不要强行下结论；先说明可见证据不足，并建议扩大时间窗口或确认 trace id/project。
- 如果 Langfuse 旧版 `/api/public/traces/<trace_id>` 返回 502，不要卡住；脚本使用 v2 observations API 作为主路径。
