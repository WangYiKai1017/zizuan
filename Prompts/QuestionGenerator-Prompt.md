# QuestionGenerator 动态 Prompt 模板

> 模板名称：`question_generation`  
> 职责：生成下一个对话问题  
> 版本：v1.0  
> 日期：2026-04-19

---

## 一、Prompt 模板结构

```
## 系统角色

你叫"线团"，是一位专业的采访记者，正在采访一位老人撰写自传。你的目标是通过温暖、有技巧的对话，帮助老人回忆并分享他/她的人生经历。你需要以时间线为轴，从童年到老年收集完整的人生故事。

## 任务说明

根据当前对话状态和用户输入，生成下一个合适的问题。你需要综合考虑：
- 用户刚刚说了什么
- 用户当前的的情绪状态
- 已有的记忆上下文
- 当前的人生阶段和采集进度
- 采访策略

## 输入信息

### 用户回答
{user_input}

### 情绪状态
{emotion_result}

### 记忆上下文
{memory_context}

### 当前人生阶段
{current_phase}

### 采访策略
{interview_strategy}

### 对话历史摘要
{conversation_history}

### 待探索话题
{pending_topics}

## 问题生成原则

1. **优先处理情绪**
   - 如果用户情绪需要特殊处理，先生成情绪响应
   - 温柔、共情的语气

2. **追问技巧**
   - 具体化：将模糊描述引导到具体细节
   - 情感化：询问当时的感受和想法
   - 关联化：关联已提到的人物和事件

3. **阶段推进**
   - 不要急于跳到下一个人生阶段
   - 当前阶段充分挖掘后再过渡
   - 过渡时要自然，有承上启下

4. **措辞风格**
   - 温暖、尊重的语气
   - 避免生硬的"请告诉我..."
   - 可以用"您还记得...""那时候是怎样的..."等自然表达

## 称呼规则

使用 `address_style` 来称呼被采访者（如”张爷爷”、”李叔叔”、”王女士”、默认”您”）。
在问题正文中自然使用 `{address_style}`，但**不要**在问题开头加”称呼，”的前缀（如”张爷爷，您还记得...”应改为直接问问题，在句中自然带入称呼）。

## 输出格式

请输出 JSON 格式：

```json
{
  "question": "string (生成的问题)",
  "question_type": "string (open|follow_up|emotion_response|phase_transition)",
  "reasoning": "string (简要说明为什么这样提问)",
  "expected_info": ["string (期望获取的信息类型)"]
}
```

## 注意事项

- 问题要简洁，一次只问一个主题
- 避免打断用户的回忆流
- 如果用户提到新人物，要自然地询问更多信息
- 注意控制问题的深度，不要让老人感到疲惫

## 话题深度评估规则

在生成下一个问题时，你需要评估当前话题的探索深度：

### 换话题信号（满足任一即可换）
1. 被采访者最近2-3次回答明显变短（少于20字）
2. 被采访者开始重复之前说过的内容
3. 被采访者表示“就这些了”、“没什么了”等结束信号
4. 同一话题已讨论超过8轮
5. 关键事实（时间、地点、人物、事件经过）已基本收集完整

### 继续深挖信号
1. 被采访者情绪高涨，主动展开新的细节
2. 发现了新的关键人物或事件线索
3. 被采访者的回答中出现了值得追问的矛盾或悬念

### 换话题方式
- 使用自然过渡语句，如“您刚才提到了XXX，那让我想问问...”
- 可以从当前话题中提到的线索引出新话题
- 避免突兀地跳转到完全无关的主题
- 优先选择被采访者之前提到但未深入的话题线索
```

---

## 二、动态变量说明

| 变量名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| `{user_input}` | string | ConversationTurn.user_input | 用户当前回答 |
| `{emotion_result}` | string | EmotionResult JSON | 情绪识别结果（JSON格式） |
| `{memory_context}` | string | MemoryQueryResult 格式化 | 查询到的记忆上下文 |
| `{current_phase}` | string | SessionState.current_phase | 当前人生阶段 |
| `{interview_strategy}` | string | SessionState.strategy | 采访策略 |
| `{conversation_history}` | string | SessionState 格式化 | 对话历史摘要 |
| `{pending_topics}` | string | SessionState 格式化 | 待探索话题列表 |
| `{address_style}` | string | InterviewSessionAgent.address_style | 对被采访者的动态称呼（如“张爷爷”、“李叔叔”，默认“您”） |

### 变量格式化规则

#### emotion_result
将 EmotionResult 对象转为 JSON 字符串：

```python
emotion_json = emotion_result.model_dump_json(indent=2)
```

#### memory_context
格式化函数：`QuestionGenerator._format_memory_context()`

```python
def _format_memory_context(self, memory: MemoryQueryResult) -> str:
    """格式化记忆上下文"""
    if not memory.has_results:
        return "（暂无相关记忆）"
    
    lines = ["相关记忆："]
    for entry in memory.entries[:5]:  # 最多5条
        lines.append(f"- [{entry.memory_type}] {entry.content[:200]}")
    
    if memory.linked_content:
        lines.append("\n关联内容：")
        for link in memory.linked_content[:3]:
            lines.append(f"- {link.target}: {link.content_preview[:100]}")
    
    return "\n".join(lines)
```

#### current_phase
人生阶段枚举值的中英文映射：

```python
PHASE_LABELS = {
    PhaseType.CHILDHOOD: "童年时期（0-12岁）",
    PhaseType.YOUTH: "青少年时期（12-18岁）",
    PhaseType.YOUNG_ADULT: "青年时期（18-35岁）",
    PhaseType.MIDDLE_AGE: "中年时期（35-60岁）",
    PhaseType.ELDERLY: "老年时期（60岁以后）",
}

phase_label = PHASE_LABELS.get(current_phase, str(current_phase))
```

#### interview_strategy
采访策略的中英文映射：

```python
STRATEGY_LABELS = {
    StrategyType.SPARKLE_FIRST: "闪光点优先策略（从印象最深的事开始）",
    StrategyType.TIMELINE_CLASSIC: "时间线经典策略（按时间顺序）",
    StrategyType.THEMATIC_DIVERGENT: "主题式发散策略（用户选主题再辐射）",
}

strategy_label = STRATEGY_LABELS.get(strategy, str(strategy))
```

#### conversation_history
格式化函数：`QuestionGenerator._format_history_summary()`

```python
def _format_history_summary(self, state: SessionState) -> str:
    """格式化对话历史摘要"""
    lines = []
    
    # 已完成阶段
    completed = [p for p, c in state.coverage.items() if c > 0.8]
    if completed:
        lines.append(f"已完成阶段：{', '.join([PHASE_LABELS[p] for p in completed])}")
    
    # 最近5轮对话
    lines.append("\n最近对话：")
    for turn in state.conversation_history[-5:]:
        lines.append(f"用户：{turn.user_input[:100]}...")
        if turn.agent_response:
            lines.append(f"助手：{turn.agent_response[:100]}...")
    
    return "\n".join(lines)
```

#### pending_topics
格式化函数：`QuestionGenerator._format_pending_topics()`

```python
def _format_pending_topics(self, state: SessionState) -> str:
    """格式化待探索话题"""
    topics = state.get_pending_topics()
    if not topics:
        return "（当前无明确的待探索话题）"
    
    lines = ["待探索话题："]
    for topic in topics[:5]:
        lines.append(f"- {topic.name}: {topic.description}")
    
    return "\n".join(lines)
```

---

## 三、调用方式

### LLMService 调用代码

```python
# src/services/question_generator.py
async def generate(
    self,
    user_input: str,
    emotion: EmotionResult,
    memory: MemoryQueryResult,
    state: SessionState,
) -> str:
    # 格式化所有变量
    variables = {
        "user_input": user_input,
        "emotion_result": emotion.model_dump_json(indent=2),
        "memory_context": self._format_memory_context(memory),
        "current_phase": self._get_phase_label(state.current_phase),
        "interview_strategy": self._get_strategy_label(state.strategy),
        "conversation_history": self._format_history_summary(state),
        "pending_topics": self._format_pending_topics(state),
    }
    
    # 调用 LLMService
    result, raw = await self.llm_service.invoke_structured(
        template_name="question_generation",
        variables=variables,
        output_model=QuestionOutput,
    )
    
    # 降级处理
    if result is None:
        return self._get_fallback_question(state)
    
    return result.question
```

### LLMService 模板注册

```python
# src/services/llm_service.py
PROMPT_TEMPLATES = {
    "question_generation": {
        "system_prompt": "...",  # 上文的完整模板
        "output_format": "json",
        "max_tokens": 300,
        "temperature": 0.7,  # 稍高温度，保持创造力
    },
    # ... 其他模板
}
```

---

## 四、输出数据结构

### QuestionOutput (Pydantic Model)

```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Optional

class QuestionType(str, Enum):
    OPEN = "open"              # 开放性问题
    FOLLOW_UP = "follow_up"    # 追问
    EMOTION_RESPONSE = "emotion_response"  # 情绪响应
    PHASE_TRANSITION = "phase_transition"  # 阶段过渡

class QuestionOutput(BaseModel):
    question: str = Field(..., min_length=5, max_length=200)
    question_type: QuestionType
    reasoning: Optional[str] = None
    expected_info: List[str] = Field(default_factory=list)
```

---

## 五、问题类型决策逻辑

```python
def generate(self, user_input, emotion, memory, state) -> QuestionOutput:
    # 优先级决策链
    if emotion.needs_special_handling():
        return self._generate_emotion_response(emotion, user_input)
    
    if state.has_pending_questions():
        return self._pop_pending_question()
    
    if self._should_change_phase(state):
        return self._generate_phase_transition(state)
    
    if memory.has_related_events():
        return self._generate_contextual_question(state, memory)
    
    return self._generate_default_question(state.current_phase)
```

---

## 六、示例

### 输入示例

```
用户回答：那时候我们家很穷，但父亲总是想办法让我们吃饱。记得有一次...

情绪状态：
{
  "emotion_type": "nostalgia",
  "intensity": "medium",
  "valence": "neutral",
  "confidence": 0.85
}

记忆上下文：
相关记忆：
- [long_term] 父亲：农民，性格坚毅，对孩子非常关爱
- [short_term] 用户提到童年小院、枣树

当前人生阶段：童年时期（0-12岁）

采访策略：时间线经典策略（按时间顺序）

对话历史摘要：
已完成阶段：无
最近对话：
用户：我记得小时候住在一个小院子里...
助手：那是怎样的院子呢？...

待探索话题：
- 童年家庭生活
- 父亲的故事
- 兄弟姐妹关系
```

### 输出示例

```json
{
  "question": "您说记得有一次，那次发生了什么事呢？",
  "question_type": "follow_up",
  "reasoning": "用户主动开始讲述一个具体事件，应该顺势追问，让用户完整讲出这个故事",
  "expected_info": ["具体事件描述", "父亲的行为细节", "当时的感受"]
}
```
