# 问答引导层 Agent 系统架构设计文档

> 面向开发者的对象设计规范  
> 版本：v1.0  
> 日期：2026-04-19

---

## 一、系统概览

### 1.1 架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        问答引导层 Agent 系统                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│                         ┌─────────────────────┐                         │
│                         │ Conversation        │                         │
│                         │ Orchestrator        │  主控制器                │
│                         └──────────┬──────────┘                         │
│                                    │                                    │
│          ┌─────────────┬───────────┼───────────┬─────────────┐          │
│          │             │           │           │             │          │
│          ▼             ▼           ▼           ▼             ▼          │
│   ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐│
│   │ Question  │ │  Memory   │ │ Knowledge │ │  Content  │ │  Emotion  ││
│   │ Generator │ │  Manager  │ │  Base     │ │ Summarizer│ │ Detector  ││
│   │           │ │           │ │ Querier   │ │           │ │           ││
│   └───────────┘ └───────────┘ └───────────┘ └───────────┘ └───────────┘│
│         │             │             │             │             │       │
│         │             │             │             │             │       │
│         └─────────────┴─────────────┼─────────────┴─────────────┘       │
│                                      │                                   │
│                         ┌────────────┴────────────┐                     │
│                         │    Memory Repository    │                     │
│                         │   (短期/长期/画像记忆)   │                     │
│                         └─────────────────────────┘                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 核心对象列表

| 对象名称 | 类型 | 职责 |
|----------|------|------|
| **ConversationOrchestrator** | 控制器 | 主控制器，协调所有子Agent，管理对话流程 |
| **LLMService** | 服务 | 大模型调用统一入口，封装LangChain/LangGraph调用 |
| **QuestionGenerator** | 服务 | 生成下一个对话问题 |
| **MemoryManager** | 服务 | 管理三层记忆的读写与更新 |
| **KnowledgeBaseQuerier** | 服务 | 查询md文件系统知识库 |
| **ContentSummarizer** | 服务 | 归纳对话内容为结构化信息 |
| **EmotionDetector** | 服务 | 识别用户情绪状态 |
| **SessionState** | 数据对象 | 会话状态，贯穿整个会话生命周期 |
| **ConversationTurn** | 数据对象 | 单轮对话记录 |
| **EmotionResult** | 数据对象 | 情绪识别结果 |
| **MemoryQueryResult** | 数据对象 | 记忆查询结果 |
| **SummaryContent** | 数据对象 | 归纳内容结构 |
| **HandoffPackage** | 数据对象 | 传递给下游Agent的数据包 |
| **MemoryRepository** | 存储层 | 记忆存储抽象层 |
| **MarkdownFileManager** | 工具 | md文件读写操作 |

---

## 二、核心控制对象

### 2.1 ConversationOrchestrator（对话主控器）

**职责**：整个问答引导层的核心控制器，协调所有子Agent异步工作，管理对话状态流转。

#### 属性

```python
class ConversationOrchestrator:
    # 子Agent引用
    question_generator: QuestionGenerator
    memory_manager: MemoryManager
    knowledge_querier: KnowledgeBaseQuerier
    content_summarizer: ContentSummarizer
    emotion_detector: EmotionDetector
    
    # 当前会话状态
    current_session: SessionState
    
    # 配置参数
    config: OrchestratorConfig
    
    # 事件总线（用于异步任务通信）
    event_bus: EventBus
```

#### 行为

| 方法名 | 输入 | 输出 | 说明 |
|--------|------|------|------|
| `process_turn(user_input)` | 用户输入文本 | AgentResponse | 处理一轮对话的核心方法 |
| `initialize_session(user_profile)` | 用户画像 | SessionState | 初始化新会话 |
| `select_strategy(user_profile)` | 用户画像 | StrategyType | 选择采访策略 |
| `handle_emotion(emotion_result)` | 情绪结果 | void | 处理情绪检测结果 |
| `check_handoff_condition()` | 无 | bool | 检查是否应传递给下游 |
| `pause_session()` | 无 | void | 暂停当前会话 |
| `resume_session(session_id)` | 会话ID | SessionState | 恢复会话 |
| `terminate_session()` | 无 | HandoffPackage | 结束会话并生成交接包 |

#### 生命周期

```
创建阶段：
  └── initialize_session() 
      ├── 创建SessionState对象
      ├── 选择采访策略
      └── 初始化记忆库连接

运行阶段：
  └── process_turn() 循环调用
      ├── 并行触发异步任务
      ├── 等待关键任务完成
      ├── 生成回复
      └── 更新状态

暂停/恢复阶段：
  ├── pause_session() → 持久化状态
  └── resume_session() → 恢复状态

销毁阶段：
  └── terminate_session()
      ├── 触发最终归纳
      ├── 生成交接包
      └── 清理资源
```

#### 与其他对象的交互

```
ConversationOrchestrator
    │
    ├──→ EmotionDetector.detect()          [异步调用]
    │       └── 返回 EmotionResult
    │
    ├──→ KnowledgeBaseQuerier.query()      [异步调用]
    │       └── 返回 MemoryQueryResult
    │
    ├──→ QuestionGenerator.generate()      [同步调用]
    │       └── 返回 Question
    │
    ├──→ ContentSummarizer.summarize()     [异步调用，不等待]
    │       └── 更新 MemoryRepository
    │
    └──→ MemoryManager
            ├── update_short_term()
            ├── update_long_term()
            └── update_profile()
```

#### 核心流程伪代码

```python
async def process_turn(self, user_input: str) -> AgentResponse:
    """
    处理一轮对话的核心方法
    """
    # 1. 创建对话轮次记录
    turn = ConversationTurn(
        turn_id=self.current_session.turn_count + 1,
        user_input=user_input,
        timestamp=datetime.now()
    )
    
    # 2. 并行启动异步任务
    emotion_task = asyncio.create_task(
        self.emotion_detector.detect(user_input, self.current_session.conversation_history)
    )
    knowledge_task = asyncio.create_task(
        self.knowledge_querier.query(user_input, self.current_session)
    )
    
    # 内容归纳延迟执行
    summary_task = asyncio.create_task(
        self.content_summarizer.summarize_async(user_input, turn.turn_id)
    )
    
    # 3. 等待关键任务（带超时保护）
    try:
        emotion_result = await asyncio.wait_for(emotion_task, timeout=self.config.emotion_timeout)
    except asyncio.TimeoutError:
        emotion_result = EmotionResult.default_neutral()
    
    try:
        knowledge_result = await asyncio.wait_for(knowledge_task, timeout=self.config.query_timeout)
    except asyncio.TimeoutError:
        knowledge_result = MemoryQueryResult.empty()
    
    # 4. 处理情绪（如有需要）
    if emotion_result.needs_special_handling():
        self.handle_emotion(emotion_result)
        if emotion_result.should_pause():
            return self.pause_and_respond(emotion_result)
    
    # 5. 生成下一个问题
    question = await self.question_generator.generate(
        user_input=user_input,
        emotion=emotion_result,
        memory=knowledge_result,
        state=self.current_session
    )
    
    # 6. 更新状态
    turn.agent_response = question
    self.current_session.add_turn(turn)
    self.current_session.update_from_emotion(emotion_result)
    
    # 7. 检查是否需要交接
    if self.check_handoff_condition():
        handoff = await self.prepare_handoff()
        self.event_bus.emit("handoff_ready", handoff)
    
    return AgentResponse(
        message=question,
        state_update=self.current_session.to_summary()
    )
```

---

## 三、服务对象

### 3.2 QuestionGenerator（问题生成器）

**职责**：根据当前状态、情绪、记忆上下文生成下一个对话问题。

#### 属性

```python
class QuestionGenerator:
    # 问题模板库
    question_templates: Dict[PhaseType, QuestionTemplateSet]
    
    # 追问策略配置
    follow_up_strategies: Dict[StrategyType, FollowUpStrategy]
    
    # 措辞风格配置
    wording_style: WordingStyleConfig
```

#### 行为

| 方法名 | 输入 | 输出 | 说明 |
|--------|------|------|------|
| `generate(user_input, emotion, memory, state)` | 多个参数 | Question | 生成下一个问题 |
| `get_open_question(phase)` | 人生阶段 | Question | 获取该阶段的开放性问题 |
| `get_follow_up_question(state, memory)` | 状态、记忆 | Question | 生成追问问题 |
| `get_emotion_response(emotion, user_input)` | 情绪、输入 | str | 生成情绪响应话术 |
| `get_phase_transition_question(from_phase, to_phase)` | 阶段切换 | Question | 生成阶段过渡问题 |

#### 生命周期

```
创建阶段：
  └── 加载问题模板库
  └── 加载措辞风格配置

运行阶段：
  └── generate() 无状态调用
      ├── 检查情绪响应需求
      ├── 检查待追问问题
      ├── 检查阶段切换
      └── 基于上下文生成问题

销毁阶段：
  └── 无特殊清理
```

#### 决策逻辑

```python
def generate(self, user_input, emotion, memory, state) -> Question:
    # 优先级决策链
    if emotion.needs_special_handling():
        return self.get_emotion_response(emotion, user_input)
    
    if state.has_pending_questions():
        return self.pop_pending_question()
    
    if self.should_change_phase(state):
        return self.get_phase_transition_question(state.current_phase, state.next_phase)
    
    if memory.has_related_events():
        return self.get_contextual_question(state, memory)
    
    return self.get_default_question(state.current_phase)
```

---

### 3.3 EmotionDetector（情绪识别器）

**职责**：识别用户输入的情绪状态，为对话策略调整提供依据。

#### 属性

```python
class EmotionDetector:
    # 情绪分类模型（可以是规则引擎或ML模型）
    emotion_model: EmotionModel
    
    # 情绪响应策略配置
    response_strategies: Dict[EmotionType, ResponseStrategy]
```

#### 行为

| 方法名 | 输入 | 输出 | 说明 |
|--------|------|------|------|
| `detect(user_input, conversation_history)` | 用户输入、对话历史 | EmotionResult | 识别情绪 |
| `get_response_strategy(emotion)` | 情绪结果 | ResponseStrategy | 获取响应策略 |
| `should_pause(emotion)` | 情绪结果 | bool | 判断是否应暂停对话 |

#### 输出数据结构

```python
class EmotionResult:
    emotion_type: str        # joy/pride/nostalgia/neutral/sadness/regret/anger/fear/fatigue
    intensity: str           # low/medium/high
    valence: str             # positive/neutral/negative
    confidence: float        # 置信度 0-1
    suggested_action: str    # continue/pause/comfort/redirect
    needs_special_handling: bool
```

---

### 3.4 KnowledgeBaseQuerier（知识库查询器）- ReAct 模式

**职责**：以 ReAct 模式动态查询 md 文件系统知识库，让大模型自主决定查询策略并判断相关记忆。

**核心设计变化**：
- **原设计**：关键词检索 → 匹配搜索 → 返回结果（被动模式）
- **新设计**：理解意图 → 动态决策 → 迭代探索 → 判断相关（ReAct 主动模式）

#### 属性

```python
class KnowledgeBaseQuerier:
    # 文件管理器
    file_manager: MarkdownFileManager
    
    # LLM 服务
    llm_service: LLMService
    
    # ReAct Agent 执行器
    agent_executor: AgentExecutor
    
    # 工具集
    tools: KnowledgeBaseTools
    
    # 查询配置
    config: QueryConfig
```

#### 行为

| 方法名 | 输入 | 输出 | 说明 |
|--------|------|------|------|
| `query(user_input, state)` | 用户输入、状态 | MemoryQueryResult | ReAct 模式查询 |
| `_build_agent()` | 无 | AgentExecutor | 构建 ReAct Agent |
| `_parse_final_answer(output)` | Agent 输出 | dict | 解析最终答案 |
| `_build_memory_result(answer)` | 答案字典 | MemoryQueryResult | 构建返回结果 |

#### 工具定义

KnowledgeBaseQuerier 提供以下工具供 ReAct Agent 调用：

| 工具名 | 参数 | 返回 | 说明 |
|--------|------|------|------|
| `list_files` | path (可选) | 文件列表 | 列出知识库文件 |
| `read_file` | file_path | 文件内容 | 读取指定文件 |
| `search_content` | keyword, limit | 匹配列表 | 全文搜索 |
| `follow_links` | file_path, depth | 关联内容 | 追踪 Wiki 链接 |

#### ReAct 查询流程

```python
async def query(self, user_input: str, state: SessionState) -> MemoryQueryResult:
    """
    ReAct 模式查询知识库
    
    大模型通过 Thought → Action → Observation 循环：
    1. Thought: 理解用户意图，决定下一步行动
    2. Action: 调用工具（list_files/read_file/search_content/follow_links）
    3. Observation: 获取工具返回结果
    4. 循环直到判断信息足够，输出 Final Answer
    """
    try:
        # 执行 ReAct Agent
        result = await self.agent_executor.ainvoke({
            "user_input": user_input,
            "available_tools": self._get_tools_description(),
        })
        
        # 解析最终答案
        final_answer = self._parse_final_answer(result["output"])
        
        # 构建并返回 MemoryQueryResult
        return self._build_memory_result(final_answer)
        
    except Exception as e:
        logger.error(f"Knowledge base query failed: {e}")
        return MemoryQueryResult.empty()
```

#### ReAct 循环示例

```
用户输入：我记得小时候住在一个小院子里，有一棵枣树...

Thought: 用户提到童年的小院和枣树，我需要查找是否有相关的记录。
Action: search_content
Action Input: {"keyword": "枣树", "limit": 5}

Observation: [
  {"file_path": "events/童年记忆.md", "matched_text": "院子里有一棵大枣树..."},
  {"file_path": "people/父亲.md", "matched_text": "父亲常在枣树下乘凉..."}
]

Thought: 找到了两个相关文件。我应该读取这些文件获取更多上下文。
Action: read_file
Action Input: {"file_path": "events/童年记忆.md"}

Observation: # 童年记忆\n## 小院\n小时候住在一个小院子里...

Thought: 我已经获取了足够的信息。现在可以输出最终答案了。

Final Answer:
{
  "query_intent": "查询用户童年时期关于小院和枣树的记忆",
  "related_memories": [
    {
      "source": "events/童年记忆.md",
      "content": "小时候住在一个小院子里，院子里有一棵大枣树",
      "relevance": "直接匹配用户描述",
      "memory_type": "long_term"
    }
  ],
  ...
}
```

#### 与其他对象的交互

```
ConversationOrchestrator
    │
    └──→ KnowledgeBaseQuerier.query()    [异步调用]
            │
            ├──→ LLMService.get_langchain_llm()
            │       └── 返回 LangChain LLM 实例
            │
            ├──→ KnowledgeBaseTools (4个工具)
            │       ├── list_files()
            │       ├── read_file()
            │       ├── search_content()
            │       └── follow_links()
            │       └── 调用 MarkdownFileManager
            │
            └── 返回 MemoryQueryResult（经过 LLM 判断的相关记忆）
```

#### Prompt 模板

使用 `knowledge_base_react` 模板，详见：`Prompts/KnowledgeBaseQuerier-Prompt.md`

---

### 3.5 ContentSummarizer（内容归纳器）

**职责**：将对话内容归纳为结构化信息，更新记忆库。

#### 属性

```python
class ContentSummarizer:
    # 信息抽取模型
    extraction_model: ExtractionModel
    
    # 记忆管理器引用
    memory_manager: MemoryManager
    
    # 归纳配置
    config: SummarizerConfig
```

#### 行为

| 方法名 | 输入 | 输出 | 说明 |
|--------|------|------|------|
| `summarize_async(user_input, turn_id)` | 用户输入、轮次ID | void | 异步归纳（不阻塞） |
| `extract_structured_info(user_input)` | 用户输入 | ExtractedInfo | 提取结构化信息 |
| `should_trigger_summary(state)` | 状态 | bool | 判断是否应触发归纳 |
| `prepare_handoff(session_state)` | 会话状态 | HandoffPackage | 准备交接包 |

#### 触发机制

```python
# 归纳触发条件
TRIGGER_CONDITIONS = [
    ("turn_count", lambda s: s.turn_count % 3 == 0),  # 每3轮
    ("phase_complete", lambda s: s.current_phase_complete),
    ("session_pause", lambda s: s.is_pausing),
    ("event_detected", lambda s: s.has_complete_event),
]
```

---

### 3.6 MemoryManager（记忆管理器）

**职责**：统一管理三层记忆的读写操作。

#### 属性

```python
class MemoryManager:
    # 存储层引用
    repository: MemoryRepository
    
    # 缓存
    short_term_cache: Dict[str, Any]
    
    # 配置
    config: MemoryConfig
```

#### 行为

| 方法名 | 输入 | 输出 | 说明 |
|--------|------|------|------|
| `update_short_term(key, value)` | 键值 | void | 更新短期记忆 |
| `update_long_term(extracted_info)` | 提取信息 | void | 更新长期记忆（md文件） |
| `update_profile(extracted_info)` | 提取信息 | void | 更新画像记忆 |
| `get_short_term(key)` | 键 | Any | 获取短期记忆 |
| `query_long_term(query)` | 查询条件 | List[MemoryEntry] | 查询长期记忆 |
| `clear_short_term()` | 无 | void | 清空短期记忆 |

#### 三层记忆访问模式

```
短期记忆：内存读写，速度最快，容量有限
    └── 存储：当前对话上下文、最近提到的实体

长期记忆：文件系统读写，持久化存储
    └── 存储：事件、人物、时间线（md文件）

画像记忆：结构化存储，支持关联查询
    └── 存储：人物画像、关系网络、主题标签
```

---

## 四、数据对象

### 4.1 SessionState（会话状态）

**职责**：记录整个会话的状态信息，贯穿会话生命周期。

#### 属性

```python
class SessionState:
    # 基本信息
    session_id: str
    created_at: datetime
    last_activity: datetime
    
    # 状态
    current_state: StateType           # INIT/WARMUP/COLLECT/DEEPEN/REDIRECT/PAUSE
    current_phase: PhaseType           # childhood/youth/young_adult/middle_age/elderly
    strategy: StrategyType             # sparkle_first/timeline_classic/thematic_divergent
    
    # 进度
    turn_count: int
    coverage: Dict[PhaseType, float]   # 各阶段覆盖率
    
    # 采集内容
    collected_events: List[str]        # 事件ID列表
    collected_people: List[str]        # 人物ID列表
    
    # 当前话题
    current_topic: Optional[TopicInfo]
    
    # 情绪状态
    emotion_state: EmotionState
    
    # 待处理
    pending_questions: List[str]
    
    # 对话历史
    conversation_history: List[ConversationTurn]
    
    # 用户偏好
    user_preferences: Dict[str, Any]
```

#### 行为

| 方法名 | 说明 |
|--------|------|
| `add_turn(turn)` | 添加一轮对话 |
| `update_coverage(phase, value)` | 更新覆盖率 |
| `mark_event_collected(event_id)` | 标记事件已采集 |
| `mark_person_collected(person_id)` | 标记人物已采集 |
| `push_pending_question(question)` | 添加待追问问题 |
| `pop_pending_question()` | 获取并移除待追问问题 |
| `to_summary()` | 生成状态摘要 |
| `to_json()` | 序列化为JSON |
| `from_json(json_str)` | 从JSON反序列化 |

#### 生命周期

```
创建：会话开始时创建
    └── session_id = generate_session_id()

更新：每轮对话更新
    ├── turn_count++
    ├── last_activity = now
    ├── update_coverage()
    └── add_turn()

持久化：会话暂停时
    └── 序列化保存到文件

销毁：会话结束时
    └── 清理内存，保留归档
```

---

### 4.2 ConversationTurn（对话轮次）

**职责**：记录单轮对话的完整信息。

#### 属性

```python
class ConversationTurn:
    turn_id: int
    timestamp: datetime
    
    # 用户输入
    user_input: str
    
    # Agent回复
    agent_response: str
    
    # 提取的信息
    extracted_entities: List[Entity]
    extracted_events: List[EventPreview]
    
    # 情绪
    emotion: Optional[EmotionResult]
    
    # 来源追溯
    source_files_referenced: List[str]
```

---

### 4.3 SummaryContent（归纳内容）

**职责**：结构化的归纳结果，用于更新记忆和传递给下游。

#### 属性

```python
class SummaryContent:
    summary_id: str
    session_id: str
    turn_range: Tuple[int, int]
    created_at: datetime
    
    # 提取的信息
    extracted_info: ExtractedInfo
    
    # 记忆更新指令
    memory_updates: MemoryUpdatePlan
    
    # 待处理问题
    pending_questions: List[str]
    
    # 交接状态
    handoff_ready: bool
    handoff_reason: Optional[str]


class ExtractedInfo:
    events: List[EventInfo]
    people: List[PersonInfo]
    time_markers: List[TimeMarker]
    themes: List[ThemeInfo]


class EventInfo:
    event_id: str
    title: str
    time: str
    time_precision: str        # year/month/day
    location: str
    type: str                  # birth/education/career/marriage/...
    description: str
    details: List[str]
    participants: List[str]
    emotions: List[str]
    significance: str
    source_turns: List[int]


class PersonInfo:
    person_id: str
    name: str
    role: str                  # 父亲/母亲/配偶/朋友/同事/...
    description: str
    relation_to_protagonist: str
    source_events: List[str]
```

---

### 4.4 HandoffPackage（交接包）

**职责**：传递给下游Agent（结构化内容整理层）的数据包。

#### 属性

```python
class HandoffPackage:
    handoff_id: str
    from_agent: str            # "Agent-A"
    to_agent: str              # "Agent-B"
    timestamp: datetime
    
    # 会话信息
    session_info: SessionSummary
    
    # 采集进度
    collection_progress: Dict[PhaseType, ProgressInfo]
    
    # 采集数据
    collected_data: CollectedData
    
    # 原始对话文件路径
    raw_conversations_path: str
    
    # 待处理问题
    pending_questions: List[str]
    
    # 给下游的提示
    notes_for_agent_b: List[str]


class ProgressInfo:
    coverage: float
    events: int
    people: int


class CollectedData:
    events: List[EventInfo]
    people: List[PersonInfo]
    timeline: List[TimeMarker]
    themes: List[ThemeInfo]
```

---

## 五、存储层对象

### 5.1 MemoryRepository（记忆仓储）

**职责**：统一的三层记忆存储抽象。

#### 属性

```python
class MemoryRepository:
    # 短期记忆存储（内存/Redis）
    short_term_store: ShortTermStore
    
    # 长期记忆存储（文件系统）
    long_term_store: LongTermStore
    
    # 画像记忆存储（文件系统 + 索引）
    profile_store: ProfileStore
    
    # 配置
    config: RepositoryConfig
```

#### 行为

| 方法名 | 说明 |
|--------|------|
| `save_event(event)` | 保存事件到长期记忆 |
| `save_person(person)` | 保存人物到画像记忆 |
| `update_timeline(event)` | 更新时间线 |
| `query_events(query)` | 查询事件 |
| `query_people(query)` | 查询人物 |
| `get_timeline()` | 获取时间线 |
| `build_index()` | 构建索引 |

---

### 5.2 MarkdownFileManager（Markdown文件管理器）

**职责**：处理md文件的读写、链接追踪等操作。

#### 属性

```python
class MarkdownFileManager:
    base_path: str             # 记忆库根目录
    
    # 目录结构
    dir_structure: Dict[str, str]
```

#### 行为

| 方法名 | 输入 | 输出 | 说明 |
|--------|------|------|------|
| `create_file(path, content)` | 路径、内容 | 文件路径 | 创建md文件 |
| `read_file(path)` | 路径 | 内容 | 读取md文件 |
| `update_file(path, content)` | 路径、内容 | void | 更新md文件 |
| `append_to_file(path, content)` | 路径、内容 | void | 追加内容 |
| `search_files(keyword)` | 关键词 | 匹配结果列表 | 全文检索 |
| `extract_wikilinks(content)` | 内容 | 链接列表 | 提取Wiki链接 |
| `resolve_link(link)` | 链接 | 文件路径 | 解析链接为文件路径 |
| `follow_links(path)` | 文件路径 | 关联内容列表 | 追踪所有链接 |

#### 文件模板

```python
# 事件文件模板
EVENT_TEMPLATE = """# {title}

## 基本信息
- **时间**：{time}
- **地点**：{location}
- **事件类型**：{type}

## 事件描述
{description}

## 相关人物
{participants_section}

## 时间线关联
- [[../timeline/life-events.md#{time}|人生大事年表]]

## 关键细节
{details_section}

## 情感标签
{emotion_tags}

## 来源
- 对话记录：{source_turns}
- 确认状态：待确认 [ ]

## 待补充
{pending_items}
"""

# 人物文件模板
PERSON_TEMPLATE = """# {name}

## 基本信息
- **关系**：{relation}
- **姓名**：{name}
- **描述**：{description}

## 对主人公的影响
{influence}

## 关联事件
{related_events_section}

## 重要语录
{quotes_section}

## 来源记录
- 对话记录：{source_turns}
- 确认状态：{confirm_status}
"""
```

---

## 六、配置对象

### 6.1 OrchestratorConfig（主控器配置）

```python
class OrchestratorConfig:
    # 超时配置
    emotion_timeout: float = 3.0       # 情绪识别超时（秒）
    query_timeout: float = 5.0         # 知识库查询超时（秒）
    summary_timeout: float = 10.0      # 内容归纳超时（秒）
    
    # 触发条件
    handoff_turn_threshold: int = 10   # 交接轮数阈值
    pause_inactivity_minutes: int = 5  # 无活动暂停时间
    
    # 并发控制
    max_concurrent_tasks: int = 5
```

### 6.2 MemoryConfig（记忆配置）

```python
class MemoryConfig:
    # 短期记忆
    short_term_capacity: int = 20      # 最多保留20轮
    
    # 长期记忆
    memory_base_path: str = "memory"
    
    # 画像记忆
    profile_update_interval: int = 3   # 每3轮更新一次画像
```

---

## 七、对象交互时序图

### 7.1 单轮对话处理流程

```
用户输入
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ ConversationOrchestrator.process_turn()                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │ 阶段1: 并行启动异步任务                                          │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│   asyncio.create_task(EmotionDetector.detect())                         │
│       │                                                                 │
│       └──→ 返回 EmotionResult                                           │
│                                                                         │
│   asyncio.create_task(KnowledgeBaseQuerier.query())                     │
│       │                                                                 │
│       └──→ 查询 MarkdownFileManager.search_files()                      │
│       └──→ 查询 MarkdownFileManager.follow_links()                      │
│       └──→ 返回 MemoryQueryResult                                       │
│                                                                         │
│   asyncio.create_task(ContentSummarizer.summarize_async())              │
│       │                                                                 │
│       └──→ [后台执行，不等待]                                            │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │ 阶段2: 等待关键任务完成（带超时保护）                              │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│   emotion_result = await wait_for(emotion_task, timeout=3s)             │
│   memory_result = await wait_for(knowledge_task, timeout=5s)            │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │ 阶段3: 生成回复                                                  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│   if emotion_result.needs_special_handling():                           │
│       handle_emotion()                                                  │
│                                                                         │
│   question = QuestionGenerator.generate(                                │
│       user_input, emotion_result, memory_result, session_state          │
│   )                                                                     │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │ 阶段4: 更新状态                                                  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│   SessionState.add_turn(turn)                                           │
│   SessionState.update_from_emotion(emotion_result)                      │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │ 阶段5: 检查交接条件                                              │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│   if check_handoff_condition():                                         │
│       handoff = prepare_handoff()                                       │
│       EventBus.emit("handoff_ready", handoff)                           │
│                                                                         │
│   return AgentResponse(message=question, state_update=...)              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
    │
    ▼
返回给用户
```

### 7.2 内容归纳与记忆更新流程

```
ContentSummarizer.summarize_async()
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   extracted_info = extract_structured_info(user_input)                  │
│       │                                                                 │
│       ├── 提取 EventInfo                                                │
│       ├── 提取 PersonInfo                                               │
│       ├── 提取 TimeMarker                                               │
│       └── 提取 ThemeInfo                                                │
│                                                                         │
│   MemoryManager.update_short_term(extracted_info)                       │
│       │                                                                 │
│       └── 更新内存缓存                                                  │
│                                                                         │
│   MemoryManager.update_long_term(extracted_info)                        │
│       │                                                                 │
│       ├── 调用 MarkdownFileManager.create_file()                        │
│       │   └── 创建 events/{phase}/{event_name}.md                       │
│       │                                                                 │
│       ├── 调用 MarkdownFileManager.update_file()                        │
│       │   └── 更新 timeline/life-events.md                              │
│       │                                                                 │
│       └── 调用 MarkdownFileManager.append_to_file()                     │
│           └── 更新 index.md                                             │
│                                                                         │
│   MemoryManager.update_profile(extracted_info)                          │
│       │                                                                 │
│       ├── 更新 people/{relation}/{person_name}.md                       │
│       └── 更新人物关系网络                                              │
│                                                                         │
│   if should_handoff():                                                  │
│       HandoffPackage = prepare_handoff(session_state, extracted_info)   │
│       EventBus.emit("handoff_ready", handoff)                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 八、事件与消息

### 8.1 事件类型

```python
class EventType(Enum):
    # 对话事件
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    
    # 状态事件
    STATE_CHANGED = "state_changed"
    PHASE_CHANGED = "phase_changed"
    STRATEGY_CHANGED = "strategy_changed"
    
    # 记忆事件
    MEMORY_UPDATED = "memory_updated"
    EVENT_CREATED = "event_created"
    PERSON_CREATED = "person_created"
    
    # 情绪事件
    EMOTION_DETECTED = "emotion_detected"
    EMOTION_ALERT = "emotion_alert"        # 需要人工介入
    
    # 交接事件
    HANDOFF_READY = "handoff_ready"
    HANDOFF_COMPLETED = "handoff_completed"
    
    # 会话事件
    SESSION_STARTED = "session_started"
    SESSION_PAUSED = "session_paused"
    SESSION_RESUMED = "session_resumed"
    SESSION_TERMINATED = "session_terminated"
```

### 8.2 EventBus（事件总线）

```python
class EventBus:
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
    
    def subscribe(self, event_type: EventType, handler: Callable):
        """订阅事件"""
        pass
    
    def unsubscribe(self, event_type: EventType, handler: Callable):
        """取消订阅"""
        pass
    
    def emit(self, event_type: EventType, data: Any):
        """发布事件"""
        pass
```

### 8.3 事件订阅示例

```python
# 订阅交接事件
event_bus.subscribe(EventType.HANDOFF_READY, lambda pkg: agent_b.receive_handoff(pkg))

# 订阅情绪警报
event_bus.subscribe(EventType.EMOTION_ALERT, lambda alert: notify_human_operator(alert))

# 订阅记忆更新
event_bus.subscribe(EventType.EVENT_CREATED, lambda event: update_search_index(event))
```

---

## 九、异常处理

### 9.1 异常类型

```python
class AgentException(Exception):
    """Agent基础异常"""
    pass

class EmotionTimeoutException(AgentException):
    """情绪识别超时"""
    pass

class QueryTimeoutException(AgentException):
    """知识库查询超时"""
    pass

class MemoryUpdateException(AgentException):
    """记忆更新失败"""
    pass

class HandoffException(AgentException):
    """交接失败"""
    pass
```

### 9.2 异常处理策略

| 异常类型 | 处理策略 |
|----------|----------|
| EmotionTimeoutException | 使用默认neutral结果，继续对话 |
| QueryTimeoutException | 使用缓存结果或跳过，继续对话 |
| MemoryUpdateException | 加入重试队列，不阻塞对话 |
| HandoffException | 记录日志，稍后重试 |

---

## 十、接口定义

### 10.1 主接口

```python
class IConversationOrchestrator(Protocol):
    """对话主控器接口"""
    
    async def process_turn(self, user_input: str) -> AgentResponse:
        ...
    
    async def initialize_session(self, user_profile: UserProfile) -> SessionState:
        ...
    
    async def terminate_session(self) -> HandoffPackage:
        ...


class IQuestionGenerator(Protocol):
    """问题生成器接口"""
    
    async def generate(
        self,
        user_input: str,
        emotion: EmotionResult,
        memory: MemoryQueryResult,
        state: SessionState
    ) -> Question:
        ...


class IEmotionDetector(Protocol):
    """情绪识别器接口"""
    
    async def detect(
        self,
        user_input: str,
        conversation_history: List[ConversationTurn]
    ) -> EmotionResult:
        ...


class IKnowledgeBaseQuerier(Protocol):
    """知识库查询器接口"""
    
    async def query(
        self,
        user_input: str,
        state: SessionState
    ) -> MemoryQueryResult:
        ...


class IContentSummarizer(Protocol):
    """内容归纳器接口"""
    
    async def summarize_async(
        self,
        user_input: str,
        turn_id: int
    ) -> None:
        ...


class IMemoryManager(Protocol):
    """记忆管理器接口"""
    
    def update_short_term(self, key: str, value: Any) -> None:
        ...
    
    def update_long_term(self, info: ExtractedInfo) -> None:
        ...
    
    def update_profile(self, info: ExtractedInfo) -> None:
        ...
```

---

## 十一、部署架构

### 11.1 单进程部署

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           单进程部署                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                        Python 进程                               │   │
│   │                                                                   │   │
│   │   ConversationOrchestrator                                       │   │
│   │        ├── QuestionGenerator                                     │   │
│   │        ├── EmotionDetector                                       │   │
│   │        ├── KnowledgeBaseQuerier                                  │   │
│   │        ├── ContentSummarizer                                     │   │
│   │        └── MemoryManager                                         │   │
│   │                                                                   │   │
│   │   MemoryRepository                                               │   │
│   │        ├── 短期记忆 (内存)                                        │   │
│   │        └── 长期记忆 (文件系统)                                    │   │
│   │                                                                   │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 11.2 微服务部署（可选）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          微服务部署架构                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐   │
│   │ 对话服务        │     │ 记忆服务        │     │ 归纳服务        │   │
│   │ Orchestrator   │────→│ Memory Manager │←────│ Summarizer     │   │
│   │ Question Gen   │     │ Query Service  │     │                 │   │
│   │ Emotion Det    │     │                 │     │                 │   │
│   └─────────────────┘     └─────────────────┘     └─────────────────┘   │
│            │                      │                      │              │
│            │                      │                      │              │
│            ▼                      ▼                      ▼              │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                        消息队列 (Kafka/RabbitMQ)                 │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                   │                                     │
│                                   ▼                                     │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                     存储 (Redis + File System)                   │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 十二、开发任务分解

### 12.1 任务列表

| 序号 | 任务 | 优先级 | 依赖 |
|------|------|--------|------|
| 1 | 实现数据对象（SessionState, EmotionResult等） | P0 | 无 |
| 2 | 实现MarkdownFileManager | P0 | 无 |
| 3 | 实现MemoryRepository | P0 | 2 |
| 4 | 实现MemoryManager | P0 | 3 |
| 5 | 实现EmotionDetector | P0 | 1 |
| 6 | 实现KnowledgeBaseQuerier | P0 | 2 |
| 7 | 实现QuestionGenerator | P0 | 1 |
| 8 | 实现ContentSummarizer | P1 | 3, 4 |
| 9 | 实现EventBus | P1 | 无 |
| 10 | 实现ConversationOrchestrator | P0 | 5, 6, 7, 8 |
| 11 | 实现HandoffPackage生成 | P1 | 10 |
| 12 | 编写单元测试 | P0 | 1-11 |
| 13 | 编写集成测试 | P1 | 12 |

### 12.2 开发顺序建议

```
阶段1: 基础设施（1-2天）
  └── 数据对象 + MarkdownFileManager + MemoryRepository

阶段2: 核心服务（2-3天）
  └── EmotionDetector + KnowledgeBaseQuerier + QuestionGenerator

阶段3: 组装与协调（2天）
  └── ContentSummarizer + ConversationOrchestrator

阶段4: 测试与优化（2天）
  └── 单元测试 + 集成测试 + 性能优化
```

---

## 十三、总结

### 对象关系总览

```
ConversationOrchestrator (主控制器)
    │
    ├── 持有 → SessionState (会话状态)
    │
    ├── 调用 → EmotionDetector (情绪识别)
    │              └── 返回 EmotionResult
    │
    ├── 调用 → KnowledgeBaseQuerier (知识库查询)
    │              ├── 使用 MarkdownFileManager
    │              └── 返回 MemoryQueryResult
    │
    ├── 调用 → QuestionGenerator (问题生成)
    │              └── 返回 Question
    │
    ├── 调用 → ContentSummarizer (内容归纳)
    │              ├── 使用 MemoryManager
    │              └── 返回 SummaryContent
    │
    └── 生成 → HandoffPackage (交接包)
                   └── 传递给下游 Agent-B
```

### 核心设计原则

1. **异步优先**：所有耗时操作异步执行，不阻塞主流程
2. **超时保护**：关键任务设置超时，失败时使用降级策略
3. **状态分离**：SessionState独立管理，支持暂停/恢复
4. **存储抽象**：MemoryRepository统一接口，便于更换存储
5. **事件驱动**：EventBus解耦组件，支持扩展

---

**文档完成**，开发者可按此规范进行实现。
