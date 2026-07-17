 我看完了 trace `8d9b3b88a0a04e60a01a0847cf519f89`。这是线上 `develop @ 6d5ff76` 的一次 `/api/interview/start` 超时。

**结论**
这次不是文件 IO 慢，也不是单个模型调用特别慢，而是 `/interview/start` 在返回任何 SSE 事件前，同步执行了老用户恢复流程里的知识库 ReAct Agent。这个 Agent 连续跑了多轮 LLM 工具循环，累计吃到 29.99s，被 SSE/客户端取消。结果是 `events_emitted=0`、`events_sent=0`，用户侧看起来就是启动一直超时。

**Trace 关键事实**
- 时间：2026-06-08 20:56:18 到 20:56:48，Asia/Shanghai
- route：`POST /interview/start`
- user：`user_1780406830166`
- session：`sess_20260607_224938_1ed7a645`
- API 总耗时：`29.989s`
- API 状态：`cancelled`
- SSE 事件：`events_emitted=0`，`events_sent=0`
- 总 observation：`58`
- 总 token：`45022`

耗时拆解：

```text
api.interview.start                         29.989s cancelled
interview.start                             29.987s
resume.analyze_needed_knowledge              1.201s
resume.kb_query                             28.758s
knowledge_base.react_agent                  28.759s ERROR cancelled
```

**具体发生了什么**
`resume.analyze_needed_knowledge` 的历史对话输入是空的：

```text
## 历史对话记录
```

所以模型输出了一个非常泛化的查询：

```text
童年时期的家庭生活和学校经历
```

这个查询其实很像 prompt 示例里的第一个例子，不是基于真实历史对话分析出来的。

随后 `resume.kb_query` 启动 `KnowledgeBaseQuerier` 的 ReAct Agent。它做了这些事：

- `list_files`
- 读取 `user.md`
- 读取 `people/protagonist.md`
- 读取 `events/childhood/杜家平因脱女同学裤子被叫家长.md`
- 读取 `timeline/life-events.md`
- 读取 `sessions/session_2026-06-02_22-56.md`
- 读取 `sessions/session_2026-06-03_22-49.md`
- `mark_suspected_file` 多个文件
- `follow_links`
- 读取 `index.md`、`summary_index.md`
- 检查 `events/youth`
- 检查 `themes`
- 读取 `events/middle_age/杜家平上学期间脱女孩裤子被叫家长.md`
- `get_exploration_report`
- 最后一轮模型准备生成最终答案时被取消

工具调用本身几乎都是毫秒级，真正耗时是多轮模型调用：

```text
1.895s
4.631s
4.579s
2.658s
3.317s
3.826s
2.246s
最后一轮 5.473s 后被取消
```

**根因**
1. `/api/interview/start` 首包被重活阻塞  
代码在 [src/service/routes/interview.py](/Users/landi/YiJia/zizuan/src/service/routes/interview.py:161) 里是先 `await runner.start()`，等全部启动逻辑完成后才开始 `async for chunk in emitter.stream()`。所以即使后面是 SSE，启动阶段没有任何事件能先发给前端。

2. 老用户恢复流程同步跑了重型 KB ReAct Agent  
在 [src/agents/interview_session_agent.py](/Users/landi/YiJia/zizuan/src/agents/interview_session_agent.py:213)：
- 先取最近 conversation JSON
- 再让模型分析要查什么
- 再同步跑知识库 ReAct 查询
- 最后才生成开场白

但这个用户没有 `conversation_*.json`，只有 `sessions/session_*.md`，所以 history 为空，导致分析模型给了泛化查询。

3. `max_iterations` 标注和实际不一致  
外层 metadata 写的是 `max_iterations=5`，但 trace 里 ReAct Agent metadata 是 `max_iterations=7`、`recursion_limit=18`。也就是说 `KnowledgeQueryTool.query(... max_iterations=5)` 没有真正传递到 `KnowledgeBaseQuerier`，实际仍按类常量跑 7 轮。

4. ReAct Agent 对启动场景太重  
启动会话只需要一个“欢迎回来 + 续聊方向”，但现在用通用知识库 Agent 做开放式探索。这个 Agent 会一轮轮读文件、思考、再读文件，随着上下文膨胀，后续每轮模型都越来越贵。

**建议修改方案**
优先级从高到低：

1. 让 `/interview/start` 在 1 秒内发首包  
不要等 `runner.start()` 完成才 stream。路由层应创建后台 task 跑启动逻辑，同时立刻进入 `emitter.stream()`。并且 `runner.start()` 要先 emit `session_started`，再做慢任务。目标是前端 30s 内至少收到 `session_started` 或 `starting`。

2. 给 `resume.kb_query` 加硬超时和降级  
在 `_resume_session()` 包一层：

```python
try:
    knowledge_context = await asyncio.wait_for(..., timeout=8)
except asyncio.TimeoutError:
    knowledge_context = ""
```

超时后继续生成开场白，不能让启动失败。

3. history 为空时跳过 `resume.analyze_needed_knowledge + resume.kb_query`  
如果 `get_latest_conversation_records()` 返回空，但 `prev_context` 已经从最新 `session_*.md` 解析出 `summary/current_topic/next_questions`，直接用这些生成开场白。这个 trace 里 KB 查询就是从空 history 被 prompt 示例带偏的。

4. 老用户恢复不要用 ReAct Agent  
启动场景建议改成确定性轻查询：读取最新 session archive、`summary_index.md`、最多 1-2 个明确相关文件。不要让模型自由探索整个知识库。

5. 修正 `max_iterations` 传递  
让 `KnowledgeQueryTool.query(max_iterations=5)` 真正传进 `KnowledgeBaseQuerier.query()`，或提供 `query(..., max_iterations)` 覆盖类常量。启动阶段建议设为 `2` 或 `3`。

6. 取消时释放半启动 session  
`start_interview.generate()` 的 `CancelledError` 分支现在只记录 cancelled。建议在 finally 里按状态释放 `SessionManager`，避免留下 `phase=init` 的僵尸 session。

7. 关闭线上 `create_agent(debug=True)`  
这会把 LangGraph state 大量打到 `logs/service.log`，虽然不是主耗时，但会制造日志 IO 和排查噪音。

**给同事的一句话版**
这个 trace 超时的直接原因是 `/api/interview/start` 在发送任何 SSE 事件前同步跑了 `resume.kb_query`，内部知识库 ReAct Agent 连续 7 轮模型调用，最终在第 29.99 秒被 SSE cancel。修复方向是：启动接口先发首包，KB 查询后台化/限时降级，history 为空时跳过泛化 KB 查询，并修正 max_iterations。