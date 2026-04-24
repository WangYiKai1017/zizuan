# ContentSummarizer 动态 Prompt 模板

> 模板名称：`content_summarization`  
> 职责：归纳对话内容为结构化信息  
> 版本：v1.0  
> 日期：2026-04-19

---

## 一、Prompt 模板结构

```
## 系统角色

你是一位专业的信息归纳专家，负责从采访对话中提取结构化信息。你需要将用户的故事转化为可供写作使用的结构化记录。

## 任务说明

分析对话内容，提取以下信息：
1. **事件**：发生了什么事？时间、地点、人物、经过
2. **人物**：提到了哪些人？他们的身份、关系、特征
3. **情感**：用户的情感体验和态度
4. **细节**：值得记录的生动细节

## 输入信息

### 对话内容
${conversa$tion_turns}

### 已有相关记忆
${existing_memory}

### 实体提示
${entity_hints}

## 归纳原则

1. **保持真实性**
   - 忠实于用户的原话
   - 不添加未提及的信息
   - 不做主观推断

2. **结构化输出**
   - 按类型分类（事件/人物/情感/细节）
   - 标注置信度
   - 建立关联关系

3. **保留细节**
   - 生动的描述性细节要保留
   - 用户的原话（金句）要标注
   - 时间线标记要准确

4. **去重与更新**
   - 与已有记忆对比，避免重复
   - 新信息补充到已有记录
   - 冲突信息需标注

## 输出格式

请严格按照以下 JSON Schema 使用中文进行 输出：

```json
{
  "summary_id": "string (唯一ID，格式：summary_YYYYMMDD_HHMMSS)",
  "time_range": {
    "start": "string (对话开始时间)",
    "end": "string (对话结束时间)"
  },
  "events": [
    {
      "event_id": "string",
      "title": "string (事件标题)",
      "description": "string (事件描述)",
      "time_period": "string (时间段，如'1960年代童年')",
      "location": "string (地点)",
      "participants": ["string (参与者ID)"],
      "significance": "string (事件意义)",
      "confidence": "number (0-1)"
    }
  ],
  "people": [
    {
      "person_id": "string",
      "name": "string",
      "role": "string (角色，如'父亲'、'同学')",
      "description": "string (描述)",
      "mentioned_count": "number",
      "first_mentioned": "string (首次提到的对话轮次)",
      "key_quotes": ["string (关于这个人的原话)"]
    }
  ],
  "emotions": [
    {
      "emotion_type": "string",
      "context": "string (触发情境)",
      "expression": "string (用户表达方式)",
      "intensity": "string (low|medium|high)"
    }
  ],
  "details": [
    {
      "type": "string (sensory|dialogue|action)",
      "content": "string (细节内容)",
      "source_turn": "number (来源对话轮次)"
    }
  ],
  "timeline_updates": [
    {
      "period": "string (人生阶段)",
      "new_info": "string (新增信息)",
      "completeness": "number (0-1)"
    }
  ],
  "relationships": [
    {
      "person1": "string",
      "person2": "string",
      "relation": "string",
      "evidence": "string (证据)"
    }
  ],
  "quality_score": "number (整体信息质量评分 0-1)",
  "notes": "string (归纳备注)"
}
```

## 注意事项

- 如果信息不确定，标注低置信度
- 如果与已有记忆冲突，在 notes 中说明
- 保留用户的原话，不要过度改写
```

---

## 二、动态变量说明

| 变量名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| `${conversation_turns}` | string | 多个 ConversationTurn | 多轮对话内容的格式化文本 |
| `${existing_memory}` | string | MemoryQueryResult | 已有的相关记忆 |
| `${entity_hints}` | string | NLP 提取 | 实体提示（人名、地名、时间等） |

### 变量格式化规则

#### conversation_turns
格式化函数：`ContentSummarizer._format_turns()`

```python
def _format_turns(self, turns: List[ConversationTurn]) -> str:
    """格式化多轮对话"""
    lines = []
    for i, turn in enumerate(turns, 1):
        lines.append(f"### 第 {i} 轮对话")
        lines.append(f"时间：{turn.timestamp.strftime('%H:%M:%S')}")
        lines.append(f"用户：{turn.user_input}")
        if turn.agent_response:
            lines.append(f"助手：{turn.agent_response}")
        lines.append("")
    return "\n".join(lines)
```

#### existing_memory
格式化函数：`ContentSummarizer._format_existing_memory()`

```python
def _format_existing_memory(self, memory: MemoryQueryResult) -> str:
    """格式化已有记忆"""
    if not memory.has_results:
        return "（暂无相关已有记忆）"
    
    lines = ["已有相关记忆："]
    for entry in memory.entries[:3]:
        lines.append(f"- [{entry.memory_type}] {entry.source}")
        lines.append(f"  {entry.content[:200]}")
    
    return "\n".join(lines)
```

#### entity_hints
格式化函数：`ContentSummarizer._extract_entity_hints()`

```python
def _extract_entity_hints(self, turns: List[ConversationTurn]) -> str:
    """提取实体提示"""
    # 简单的实体提取（可以使用 NER 模型增强）
    text = " ".join([t.user_input for t in turns])
    
    hints = []
    
    # 时间词
    time_patterns = ["小时候", "童年", "那年", "那时候", "年轻时"]
    for p in time_patterns:
        if p in text:
            hints.append(f"- 时间提示：{p}")
    
    # 人物词（简单的代词检测）
    if "父亲" in text or "爸爸" in text:
        hints.append("- 人物提示：父亲")
    if "母亲" in text or "妈妈" in text:
        hints.append("- 人物提示：母亲")
    
    # 地名词（简单的地点检测）
    location_patterns = ["家里", "院子", "学校", "村里", "城里"]
    for p in location_patterns:
        if p in text:
            hints.append(f"- 地点提示：{p}")
    
    return "\n".join(hints) if hints else "（未检测到明显实体提示）"
```

---

## 三、调用方式

### LLMService 调用代码

```python
# src/services/content_summarizer.py
async def summarize_async(
    self,
    turns: List[ConversationTurn],
    existing_memory: MemoryQueryResult,
) -> SummaryContent:
    """异步归纳对话内容"""
    
    # 格式化变量
    variables = {
        "conversation_turns": self._format_turns(turns),
        "existing_memory": self._format_existing_memory(existing_memory),
        "entity_hints": self._extract_entity_hints(turns),
    }
    
    # 调用 LLMService
    result, raw = await self.llm_service.invoke_structured(
        template_name="content_summarization",
        variables=variables,
        output_model=SummaryContent,
    )
    
    # 降级处理
    if result is None:
        return SummaryContent.empty()
    
    # 更新记忆库
    await self._update_memory(result)
    
    return result
```

### LLMService 模板注册

```python
# src/services/llm_service.py
PROMPT_TEMPLATES = {
    "content_summarization": {
        "system_prompt": "...",  # 上文的完整模板
        "output_format": "json",
        "max_tokens": 2000,  # 归纳内容可能较长
        "temperature": 0.3,  # 低温度，保持准确性
    },
    # ... 其他模板
}
```

---

## 四、输出数据结构

### SummaryContent (Pydantic Model)

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class EventInfo(BaseModel):
    event_id: str
    title: str
    description: str
    time_period: Optional[str] = None
    location: Optional[str] = None
    participants: List[str] = Field(default_factory=list)
    significance: Optional[str] = None
    confidence: float = Field(ge=0, le=1, default=0.5)

class PersonInfo(BaseModel):
    person_id: str
    name: str
    role: Optional[str] = None
    description: str
    mentioned_count: int = 1
    first_mentioned: Optional[str] = None
    key_quotes: List[str] = Field(default_factory=list)

class EmotionInfo(BaseModel):
    emotion_type: str
    context: str
    expression: str
    intensity: str = "medium"  # low | medium | high

class DetailInfo(BaseModel):
    type: str  # sensory | dialogue | action
    content: str
    source_turn: int

class TimelineUpdate(BaseModel):
    period: str
    new_info: str
    completeness: float = Field(ge=0, le=1)

class RelationshipInfo(BaseModel):
    person1: str
    person2: str
    relation: str
    evidence: Optional[str] = None

class TimeRange(BaseModel):
    start: str
    end: str

class SummaryContent(BaseModel):
    summary_id: str
    time_range: TimeRange
    events: List[EventInfo] = Field(default_factory=list)
    people: List[PersonInfo] = Field(default_factory=list)
    emotions: List[EmotionInfo] = Field(default_factory=list)
    details: List[DetailInfo] = Field(default_factory=list)
    timeline_updates: List[TimelineUpdate] = Field(default_factory=list)
    relationships: List[RelationshipInfo] = Field(default_factory=list)
    quality_score: float = Field(ge=0, le=1, default=0.5)
    notes: Optional[str] = None
    
    @classmethod
    def empty(cls) -> "SummaryContent":
        now = datetime.now()
        return cls(
            summary_id=f"summary_{now.strftime('%Y%m%d_%H%M%S')}",
            time_range=TimeRange(start="", end=""),
        )
    
    def to_markdown(self) -> str:
        """转换为 Markdown 格式存储"""
        lines = [f"# {self.summary_id}", ""]
        
        if self.events:
            lines.append("## 事件")
            for e in self.events:
                lines.append(f"- **{e.title}** ({e.time_period or '时间未知'})")
                lines.append(f"  {e.description}")
            lines.append("")
        
        if self.people:
            lines.append("## 人物")
            for p in self.people:
                lines.append(f"- **{p.name}** ({p.role or '角色未知'})")
                lines.append(f"  {p.description}")
            lines.append("")
        
        # ... 其他内容
        
        return "\n".join(lines)
```

---

## 五、触发机制

### 归纳触发条件

```python
# src/services/content_summarizer.py
from dataclasses import dataclass
from typing import Callable

@dataclass
class SummaryTrigger:
    name: str
    condition: Callable[[SessionState], bool]
    priority: int

TRIGGERS = [
    SummaryTrigger(
        name="turn_count",
        condition=lambda s: s.turn_count > 0 and s.turn_count % 3 == 0,
        priority=1,
    ),
    SummaryTrigger(
        name="phase_complete",
        condition=lambda s: s.current_phase_complete,
        priority=2,
    ),
    SummaryTrigger(
        name="session_pause",
        condition=lambda s: s.is_pausing,
        priority=3,
    ),
    SummaryTrigger(
        name="event_detected",
        condition=lambda s: s.has_complete_event,
        priority=4,
    ),
]

def should_trigger_summary(state: SessionState) -> Optional[str]:
    """判断是否应触发归纳"""
    for trigger in sorted(TRIGGERS, key=lambda t: t.priority):
        if trigger.condition(state):
            return trigger.name
    return None
```

### 归纳后的存储

```python
async def _update_memory(self, summary: SummaryContent) -> None:
    """更新记忆库"""
    # 1. 更新事件
    for event in summary.events:
        await self.memory_manager.update_long_term(
            category="events",
            entry_id=event.event_id,
            content=event.model_dump_json(),
        )
    
    # 2. 更新人物
    for person in summary.people:
        await self.memory_manager.update_profile(
            category="people",
            person_id=person.person_id,
            content=person.model_dump_json(),
        )
    
    # 3. 更新时间线
    for update in summary.timeline_updates:
        await self.memory_manager.update_long_term(
            category="timeline",
            entry_id=update.period,
            content=update.model_dump_json(),
        )
```

---

## 六、示例

### 输入示例

```
对话内容：
### 第 1 轮对话
时间：14:30:15
用户：我记得小时候住在一个小院子里。
助手：那是怎样的院子呢？您还记得里面的样子吗？

### 第 2 轮对话
时间：14:30:45
用户：院子不大，但种了一棵枣树。每到秋天，我们兄弟姐妹就盼着枣子熟。
助手：听起来是很温馨的记忆。枣树是什么样子的？

### 第 3 轮对话
时间：14:31:20
用户：那棵枣树很老了，听父亲说是他小时候种的。父亲常在树下给我们讲故事。

已有相关记忆：
（暂无相关已有记忆）

实体提示：
- 时间提示：小时候
- 人物提示：父亲
- 地点提示：院子
```

### 输出示例

```json
{
  "summary_id": "summary_20260419_143130",
  "time_range": {
    "start": "14:30:15",
    "end": "14:31:20"
  },
  "events": [
    {
      "event_id": "evt_childhood_courtyard",
      "title": "童年小院生活",
      "description": "用户童年时期住在一个有小院子的小院里，院子里有一棵老枣树，是父亲小时候种的。秋天时兄弟姐妹一起盼望枣子成熟，父亲常在树下讲故事。",
      "time_period": "童年时期",
      "location": "家中院子",
      "participants": ["user", "父亲", "兄弟姐妹"],
      "significance": "温馨的家庭记忆，体现家庭氛围",
      "confidence": 0.9
    }
  ],
  "people": [
    {
      "person_id": "person_father",
      "name": "父亲",
      "role": "父亲",
      "description": "用户父亲，枣树的种植者，常在树下给孩子讲故事",
      "mentioned_count": 2,
      "first_mentioned": "第3轮",
      "key_quotes": ["那棵枣树很老了，听父亲说是他小时候种的", "父亲常在树下给我们讲故事"]
    },
    {
      "person_id": "person_siblings",
      "name": "兄弟姐妹",
      "role": "兄弟姐妹",
      "description": "与用户一起盼望枣子成熟",
      "mentioned_count": 1,
      "first_mentioned": "第2轮",
      "key_quotes": ["我们兄弟姐妹就盼着枣子熟"]
    }
  ],
  "emotions": [
    {
      "emotion_type": "nostalgia",
      "context": "回忆童年小院和枣树",
      "expression": "温馨的叙述语气",
      "intensity": "medium"
    },
    {
      "emotion_type": "joy",
      "context": "回忆盼枣子成熟的期待",
      "expression": "提到'盼望'",
      "intensity": "low"
    }
  ],
  "details": [
    {
      "type": "sensory",
      "content": "院子里有一棵老枣树",
      "source_turn": 2
    },
    {
      "type": "action",
      "content": "父亲常在树下讲故事",
      "source_turn": 3
    }
  ],
  "timeline_updates": [
    {
      "period": "童年时期",
      "new_info": "住在有小院子的家中，院里有父亲小时候种的老枣树",
      "completeness": 0.3
    }
  ],
  "relationships": [
    {
      "person1": "user",
      "person2": "父亲",
      "relation": "父子/父女",
      "evidence": "父亲常给用户讲故事"
    },
    {
      "person1": "user",
      "person2": "兄弟姐妹",
      "relation": "兄弟姐妹",
      "evidence": "一起盼望枣子成熟"
    }
  ],
  "quality_score": 0.85,
  "notes": "高质量对话，获取了清晰的事件、人物和情感信息。枣树是重要意象，后续可以深入挖掘。"
}
```
