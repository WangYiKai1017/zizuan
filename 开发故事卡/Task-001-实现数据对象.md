# 开发故事卡 - Task 1: 实现数据对象

> 任务编号：Task-001  
> 优先级：P0  
> 依赖：无  
> 预计工时：0.5天

---

## 一、任务概述

实现问答引导层Agent系统中所有数据对象（Data Objects），这些对象是整个系统的数据基础，被其他所有模块引用。

---

## 二、项目上下文

### 2.1 系统定位

本系统是「老人自传Agent系统」的**问答引导层**，负责与老人进行多轮对话，收集人生故事。系统采用Python + LangChain/LangGraph技术栈，遵循Harness范式。

### 2.2 Harness范式核心原则

```
1. Agent职责单一：每个Agent只做一件事
2. 异步并发：耗时操作异步执行，不阻塞主流程
3. 状态驱动：通过状态流转控制Agent行为
4. 记忆分层：短期/长期/画像三层记忆架构
5. 模型统一：所有大模型调用通过LLMService统一入口
```

### 2.3 技术栈

- Python 3.10+
- LangChain / LangGraph（Agent编排）
- Pydantic（数据验证）
- asyncio（异步编程）
- dataclasses / pydantic（数据对象）

---

## 三、需要实现的数据对象

### 3.1 对象列表

| 对象名 | 文件路径 | 说明 |
|--------|----------|------|
| SessionState | `models/session_state.py` | 会话状态，贯穿整个会话生命周期 |
| ConversationTurn | `models/conversation_turn.py` | 单轮对话记录 |
| EmotionResult | `models/emotion_result.py` | 情绪识别结果 |
| MemoryQueryResult | `models/memory_query_result.py` | 记忆查询结果 |
| SummaryContent | `models/summary_content.py` | 归纳内容结构 |
| HandoffPackage | `models/handoff_package.py` | 传递给下游Agent的数据包 |
| EventInfo | `models/event_info.py` | 事件信息结构 |
| PersonInfo | `models/person_info.py` | 人物信息结构 |
| AgentResponse | `models/agent_response.py` | Agent响应结构 |

### 3.2 目录结构

```
src/
├── models/
│   ├── __init__.py
│   ├── session_state.py
│   ├── conversation_turn.py
│   ├── emotion_result.py
│   ├── memory_query_result.py
│   ├── summary_content.py
│   ├── handoff_package.py
│   ├── event_info.py
│   ├── person_info.py
│   └── agent_response.py
├── enums/
│   ├── __init__.py
│   ├── state_type.py
│   ├── phase_type.py
│   ├── strategy_type.py
│   └── emotion_type.py
└── ...
```

---

## 四、详细设计

### 4.1 枚举类型定义

```python
# src/enums/state_type.py
from enum import Enum

class StateType(str, Enum):
    """对话状态枚举"""
    INIT = "init"                 # 初始化
    WARMUP = "warmup"             # 破冰阶段
    COLLECT = "collect"           # 采集阶段
    DEEPEN = "deepen"             # 深挖模式
    REDIRECT = "redirect"         # 重定向模式
    PAUSE = "pause"               # 暂停阶段
    HANDOFF = "handoff"           # 交接阶段


# src/enums/phase_type.py
from enum import Enum

class PhaseType(str, Enum):
    """人生阶段枚举"""
    CHILDHOOD = "childhood"       # 童年 0-12岁
    YOUTH = "youth"               # 少年 13-18岁
    YOUNG_ADULT = "young_adult"   # 青年 19-35岁
    MIDDLE_AGE = "middle_age"     # 中年 36-60岁
    ELDERLY = "elderly"           # 老年 60岁+


# src/enums/strategy_type.py
from enum import Enum

class StrategyType(str, Enum):
    """采访策略枚举"""
    SPARKLE_FIRST = "sparkle_first"           # 闪光点优先
    TIMELINE_CLASSIC = "timeline_classic"     # 时间线经典
    THEMATIC_DIVERGENT = "thematic_divergent" # 主题式发散


# src/enums/emotion_type.py
from enum import Enum

class EmotionType(str, Enum):
    """情绪类型枚举"""
    # 正向
    JOY = "joy"
    PRIDE = "pride"
    NOSTALGIA = "nostalgia"
    GRATITUDE = "gratitude"
    HOPE = "hope"
    
    # 中性
    NEUTRAL = "neutral"
    CURIOUS = "curious"
    CONTEMPLATIVE = "contemplative"
    
    # 负向
    SADNESS = "sadness"
    REGRET = "regret"
    ANGER = "anger"
    FEAR = "fear"
    GUILT = "guilt"
    
    # 特殊
    CONFUSION = "confusion"
    FATIGUE = "fatigue"
    RELUCTANCE = "reluctance"


class EmotionIntensity(str, Enum):
    """情绪强度枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EmotionValence(str, Enum):
    """情绪极性枚举"""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class SuggestedAction(str, Enum):
    """建议动作枚举"""
    CONTINUE = "continue"
    PAUSE = "pause"
    COMFORT = "comfort"
    REDIRECT = "redirect"
```

### 4.2 SessionState（会话状态）

```python
# src/models/session_state.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enums import StateType, PhaseType, StrategyType, EmotionType
from .conversation_turn import ConversationTurn
from .emotion_result import EmotionResult


class TopicInfo(BaseModel):
    """当前话题信息"""
    type: str                           # event/person/theme
    name: str                           # 话题名称
    start_turn: int                     # 开始轮次
    depth: int = 0                      # 挖掘深度


class EmotionState(BaseModel):
    """情绪状态"""
    emotion_type: EmotionType = EmotionType.NEUTRAL
    intensity: str = "low"
    last_change_turn: int = 0


class SessionState(BaseModel):
    """
    会话状态 - 贯穿整个会话生命周期的核心数据对象
    
    职责：
    - 记录当前会话的所有状态信息
    - 追踪对话进度和覆盖率
    - 管理采集的事件和人物
    
    使用场景：
    - ConversationOrchestrator 持有并更新
    - 所有Service对象读取状态信息
    - 暂停/恢复时持久化/反序列化
    """
    
    # 基本信息
    session_id: str = Field(..., description="会话唯一标识")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    last_activity: datetime = Field(default_factory=datetime.now, description="最后活动时间")
    
    # 状态
    current_state: StateType = Field(default=StateType.INIT, description="当前对话状态")
    current_phase: PhaseType = Field(default=PhaseType.CHILDHOOD, description="当前人生阶段")
    strategy: StrategyType = Field(default=StrategyType.SPARKLE_FIRST, description="当前采访策略")
    
    # 进度
    turn_count: int = Field(default=0, description="对话轮数")
    coverage: Dict[PhaseType, float] = Field(
        default_factory=lambda: {
            PhaseType.CHILDHOOD: 0.0,
            PhaseType.YOUTH: 0.0,
            PhaseType.YOUNG_ADULT: 0.0,
            PhaseType.MIDDLE_AGE: 0.0,
            PhaseType.ELDERLY: 0.0,
        },
        description="各阶段覆盖率"
    )
    
    # 采集内容
    collected_events: List[str] = Field(default_factory=list, description="已收集事件ID列表")
    collected_people: List[str] = Field(default_factory=list, description="已收集人物ID列表")
    
    # 当前话题
    current_topic: Optional[TopicInfo] = Field(default=None, description="当前话题")
    
    # 情绪状态
    emotion_state: EmotionState = Field(default_factory=EmotionState, description="情绪状态")
    
    # 待处理
    pending_questions: List[str] = Field(default_factory=list, description="待追问问题列表")
    
    # 对话历史
    conversation_history: List[ConversationTurn] = Field(
        default_factory=list,
        description="对话历史"
    )
    
    # 用户偏好
    user_preferences: Dict[str, Any] = Field(default_factory=dict, description="用户偏好")
    
    class Config:
        use_enum_values = True
    
    def add_turn(self, turn: ConversationTurn) -> None:
        """添加一轮对话"""
        self.conversation_history.append(turn)
        self.turn_count += 1
        self.last_activity = datetime.now()
    
    def update_coverage(self, phase: PhaseType, value: float) -> None:
        """更新覆盖率"""
        self.coverage[phase] = min(1.0, max(0.0, value))
    
    def mark_event_collected(self, event_id: str) -> None:
        """标记事件已采集"""
        if event_id not in self.collected_events:
            self.collected_events.append(event_id)
    
    def mark_person_collected(self, person_id: str) -> None:
        """标记人物已采集"""
        if person_id not in self.collected_people:
            self.collected_people.append(person_id)
    
    def push_pending_question(self, question: str) -> None:
        """添加待追问问题"""
        self.pending_questions.append(question)
    
    def pop_pending_question(self) -> Optional[str]:
        """获取并移除待追问问题"""
        return self.pending_questions.pop(0) if self.pending_questions else None
    
    def has_pending_questions(self) -> bool:
        """是否有待追问问题"""
        return len(self.pending_questions) > 0
    
    def update_from_emotion(self, emotion_result: EmotionResult) -> None:
        """从情绪结果更新状态"""
        self.emotion_state.emotion_type = emotion_result.emotion_type
        self.emotion_state.intensity = emotion_result.intensity
        self.emotion_state.last_change_turn = self.turn_count
    
    def to_summary(self) -> Dict[str, Any]:
        """生成状态摘要"""
        return {
            "session_id": self.session_id,
            "current_state": self.current_state,
            "current_phase": self.current_phase,
            "turn_count": self.turn_count,
            "coverage": self.coverage,
            "collected_events_count": len(self.collected_events),
            "collected_people_count": len(self.collected_people),
        }
    
    def get_recent_history(self, n: int = 5) -> List[ConversationTurn]:
        """获取最近n轮对话"""
        return self.conversation_history[-n:] if self.conversation_history else []
```

### 4.3 ConversationTurn（对话轮次）

```python
# src/models/conversation_turn.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional
from .event_info import EventInfo


class Entity(BaseModel):
    """实体"""
    type: str       # person/place/time/organization
    name: str
    metadata: dict = {}


class ConversationTurn(BaseModel):
    """
    对话轮次 - 记录单轮对话的完整信息
    
    职责：
    - 记录用户输入和Agent回复
    - 追踪提取的实体和事件
    - 关联情绪状态
    
    使用场景：
    - SessionState.conversation_history 的元素
    - EmotionDetector 的输入
    - ContentSummarizer 的输入
    """
    
    turn_id: int = Field(..., description="轮次ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    
    # 用户输入
    user_input: str = Field(..., description="用户输入文本")
    
    # Agent回复
    agent_response: Optional[str] = Field(default=None, description="Agent回复文本")
    
    # 提取的信息
    extracted_entities: List[Entity] = Field(default_factory=list, description="提取的实体")
    extracted_events: List[EventInfo] = Field(default_factory=list, description="提取的事件预览")
    
    # 情绪
    emotion: Optional[str] = Field(default=None, description="情绪类型")
    
    # 来源追溯
    source_files_referenced: List[str] = Field(
        default_factory=list,
        description="引用的记忆库文件"
    )
    
    # 元数据
    metadata: dict = Field(default_factory=dict, description="额外元数据")
```

### 4.4 EmotionResult（情绪识别结果）

```python
# src/models/emotion_result.py
from pydantic import BaseModel, Field
from typing import Optional
from enums import EmotionType, EmotionIntensity, EmotionValence, SuggestedAction


class EmotionResult(BaseModel):
    """
    情绪识别结果
    
    职责：
    - 记录情绪识别的完整结果
    - 提供响应建议
    
    使用场景：
    - EmotionDetector.detect() 的返回值
    - ConversationOrchestrator 根据情绪调整策略
    - QuestionGenerator 根据情绪生成响应
    """
    
    emotion_type: EmotionType = Field(..., description="情绪类型")
    intensity: EmotionIntensity = Field(default=EmotionIntensity.LOW, description="情绪强度")
    valence: EmotionValence = Field(default=EmotionValence.NEUTRAL, description="情绪极性")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")
    suggested_action: SuggestedAction = Field(
        default=SuggestedAction.CONTINUE,
        description="建议动作"
    )
    
    @property
    def needs_special_handling(self) -> bool:
        """是否需要特殊处理"""
        return (
            self.intensity == EmotionIntensity.HIGH and 
            self.valence == EmotionValence.NEGATIVE
        ) or self.emotion_type in [
            EmotionType.FATIGUE,
            EmotionType.RELUCTANCE,
            EmotionType.CONFUSION
        ]
    
    def should_pause(self) -> bool:
        """是否应该暂停"""
        return self.suggested_action in [
            SuggestedAction.PAUSE,
            SuggestedAction.COMFORT
        ]
    
    @classmethod
    def default_neutral(cls) -> "EmotionResult":
        """创建默认中性情绪结果"""
        return cls(
            emotion_type=EmotionType.NEUTRAL,
            intensity=EmotionIntensity.LOW,
            valence=EmotionValence.NEUTRAL,
            confidence=1.0,
            suggested_action=SuggestedAction.CONTINUE
        )
```

### 4.5 MemoryQueryResult（记忆查询结果）

```python
# src/models/memory_query_result.py
from pydantic import BaseModel, Field
from typing import List, Optional, Any
from datetime import datetime


class MemoryEntry(BaseModel):
    """记忆条目"""
    source: str                     # 来源文件路径
    content: str                    # 内容摘要
    relevance: float                # 相关度 0-1
    memory_type: str                # short_term/long_term/profile
    metadata: dict = {}


class LinkedContent(BaseModel):
    """链接内容"""
    source: str                     # 源文件路径
    target: str                     # 目标文件路径
    content_preview: str            # 内容预览
    relation: str = "related"       # 关联类型


class MemoryQueryResult(BaseModel):
    """
    记忆查询结果
    
    职责：
    - 封装记忆库查询的结果
    - 提供相关事件、人物、链接内容
    
    使用场景：
    - KnowledgeBaseQuerier.query() 的返回值
    - QuestionGenerator 生成问题的上下文
    - ContentSummarizer 归纳时的参考
    """
    
    query: str = Field(..., description="原始查询")
    query_time: datetime = Field(default_factory=datetime.now, description="查询时间")
    
    # 结果
    entries: List[MemoryEntry] = Field(default_factory=list, description="匹配的记忆条目")
    linked_content: List[LinkedContent] = Field(
        default_factory=list,
        description="通过链接关联的内容"
    )
    
    # 汇总
    total_count: int = Field(default=0, description="总结果数")
    has_results: bool = Field(default=False, description="是否有结果")
    
    def get_top_entries(self, n: int = 5) -> List[MemoryEntry]:
        """获取相关度最高的n个条目"""
        sorted_entries = sorted(self.entries, key=lambda x: x.relevance, reverse=True)
        return sorted_entries[:n]
    
    def get_events(self) -> List[MemoryEntry]:
        """获取事件类型的条目"""
        return [e for e in self.entries if "event" in e.source.lower()]
    
    def get_people(self) -> List[MemoryEntry]:
        """获取人物类型的条目"""
        return [e for e in self.entries if "people" in e.source.lower()]
    
    def has_related_events(self) -> bool:
        """是否有相关事件"""
        return len(self.get_events()) > 0
    
    @classmethod
    def empty(cls) -> "MemoryQueryResult":
        """创建空结果"""
        return cls(query="", entries=[], total_count=0, has_results=False)
    
    @classmethod
    def from_entries(cls, query: str, entries: List[MemoryEntry]) -> "MemoryQueryResult":
        """从条目列表创建"""
        return cls(
            query=query,
            entries=entries,
            total_count=len(entries),
            has_results=len(entries) > 0
        )
```

### 4.6 EventInfo & PersonInfo

```python
# src/models/event_info.py
from pydantic import BaseModel, Field
from typing import List, Optional


class EventInfo(BaseModel):
    """
    事件信息
    
    职责：
    - 结构化记录单个事件
    - 支持写入记忆库
    
    使用场景：
    - ContentSummarizer 的提取结果
    - MarkdownFileManager 写入文件
    - HandoffPackage 的组成部分
    """
    
    event_id: str = Field(..., description="事件ID")
    title: str = Field(..., description="事件标题")
    time: str = Field(..., description="时间描述")
    time_precision: str = Field(default="year", description="时间精度: year/month/day")
    location: str = Field(default="", description="地点")
    type: str = Field(default="other", description="事件类型")
    # birth/education/career/marriage/relocation/achievement/challenge/travel/historical/other
    
    description: str = Field(..., description="事件描述")
    details: List[str] = Field(default_factory=list, description="关键细节")
    participants: List[str] = Field(default_factory=list, description="参与人物")
    emotions: List[str] = Field(default_factory=list, description="情感标签")
    significance: str = Field(default="", description="事件意义")
    source_turns: List[int] = Field(default_factory=list, description="来源对话轮次")
    
    def to_markdown(self) -> str:
        """转换为Markdown格式"""
        details_section = "\n".join([f"- {d}" for d in self.details]) if self.details else "暂无"
        emotion_tags = " ".join([f"#{e}" for e in self.emotions]) if self.emotions else "#待补充"
        participants_section = "\n".join([f"- [[../people/{p}.md|{p}]]" for p in self.participants])
        source_turns_str = ", ".join([f"session_001, turn_{t}" for t in self.source_turns])
        
        return f"""# {self.title}

## 基本信息
- **时间**：{self.time}
- **地点**：{self.location}
- **事件类型**：{self.type}

## 事件描述
{self.description}

## 相关人物
{participants_section if self.participants else "暂无"}

## 时间线关联
- [[../timeline/life-events.md#{self.time}|人生大事年表]]

## 关键细节
{details_section}

## 情感标签
{emotion_tags}

## 来源
- 对话记录：{source_turns_str}
- 确认状态：待确认 [ ]

## 待补充
- [ ] 待补充详细信息
"""


# src/models/person_info.py
from pydantic import BaseModel, Field
from typing import List


class PersonInfo(BaseModel):
    """
    人物信息
    
    职责：
    - 结构化记录人物画像
    - 支持写入记忆库
    
    使用场景：
    - ContentSummarizer 的提取结果
    - MarkdownFileManager 写入文件
    - HandoffPackage 的组成部分
    """
    
    person_id: str = Field(..., description="人物ID")
    name: str = Field(..., description="姓名")
    role: str = Field(..., description="角色/关系")
    # immediate_family/extended_family/spouse/friend/colleague/mentor/classmate/neighbor
    
    description: str = Field(default="", description="人物描述")
    relation_to_protagonist: str = Field(default="", description="与主人公的关系")
    source_events: List[str] = Field(default_factory=list, description="相关事件ID")
    
    # 可选扩展字段
    birth_year: str = Field(default="", description="出生年份")
    characteristics: List[str] = Field(default_factory=list, description="性格特征")
    influence: str = Field(default="", description="对主人公的影响")
    quotes: List[str] = Field(default_factory=list, description="重要语录")
    
    def to_markdown(self) -> str:
        """转换为Markdown格式"""
        related_events = "\n".join([f"- [[../events/{e}.md|{e}]]" for e in self.source_events])
        quotes_section = "\n".join([f"> {q}" for q in self.quotes]) if self.quotes else "暂无"
        
        return f"""# {self.name}

## 基本信息
- **关系**：{self.role}
- **姓名**：{self.name}
- **描述**：{self.description}

## 与主人公的关系
{self.relation_to_protagonist if self.relation_to_protagonist else "待补充"}

## 对主人公的影响
{self.influence if self.influence else "待补充"}

## 相关事件
{related_events if self.source_events else "暂无"}

## 重要语录
{quotes_section}

## 来源记录
- 来源事件：{', '.join(self.source_events) if self.source_events else '无'}
- 确认状态：待确认 [ ]
"""
```

### 4.7 SummaryContent（归纳内容）

```python
# src/models/summary_content.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .event_info import EventInfo
from .person_info import PersonInfo


class TimeMarker(BaseModel):
    """时间标记"""
    time: str                       # 时间点
    events: List[str]               # 相关事件ID
    phase: str                      # 人生阶段


class ThemeInfo(BaseModel):
    """主题信息"""
    theme: str                      # 主题名称
    related_events: List[str]       # 相关事件
    description: str                # 描述


class ExtractedInfo(BaseModel):
    """提取的信息汇总"""
    events: List[EventInfo] = []
    people: List[PersonInfo] = []
    time_markers: List[TimeMarker] = []
    themes: List[ThemeInfo] = []


class MemoryUpdatePlan(BaseModel):
    """记忆更新计划"""
    short_term_updates: Dict[str, Any] = {}
    long_term_files: List[str] = []          # 需要更新的文件路径
    profile_updates: Dict[str, Any] = {}


class SummaryContent(BaseModel):
    """
    归纳内容 - 结构化的归纳结果
    
    职责：
    - 封装内容归纳的完整结果
    - 指导记忆库更新
    
    使用场景：
    - ContentSummarizer.summarize() 的输出
    - MemoryManager 更新记忆的依据
    - HandoffPackage 的组成部分
    """
    
    summary_id: str = Field(..., description="归纳ID")
    session_id: str = Field(..., description="会话ID")
    turn_range: Tuple[int, int] = Field(..., description="覆盖的对话轮次范围")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    
    # 提取的信息
    extracted_info: ExtractedInfo = Field(default_factory=ExtractedInfo)
    
    # 记忆更新指令
    memory_updates: MemoryUpdatePlan = Field(default_factory=MemoryUpdatePlan)
    
    # 待处理问题
    pending_questions: List[str] = Field(default_factory=list)
    
    # 交接状态
    handoff_ready: bool = Field(default=False)
    handoff_reason: Optional[str] = Field(default=None)
```

### 4.8 HandoffPackage（交接包）

```python
# src/models/handoff_package.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, List
from .event_info import EventInfo
from .person_info import PersonInfo
from .summary_content import TimeMarker, ThemeInfo


class ProgressInfo(BaseModel):
    """阶段进度信息"""
    coverage: float = 0.0
    events: int = 0
    people: int = 0


class SessionSummary(BaseModel):
    """会话摘要"""
    session_id: str
    total_turns: int
    duration_minutes: float
    strategy_used: str


class CollectedData(BaseModel):
    """采集数据"""
    events: List[EventInfo] = []
    people: List[PersonInfo] = []
    timeline: List[TimeMarker] = []
    themes: List[ThemeInfo] = []


class HandoffPackage(BaseModel):
    """
    交接包 - 传递给下游Agent的数据包
    
    职责：
    - 封装完整的采集结果
    - 记录采集进度和提示
    
    使用场景：
    - ConversationOrchestrator.terminate_session() 的输出
    - 传递给下游 Agent-B（结构化内容整理层）
    """
    
    handoff_id: str = Field(..., description="交接ID")
    from_agent: str = Field(default="Agent-A", description="来源Agent")
    to_agent: str = Field(default="Agent-B", description="目标Agent")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    
    # 会话信息
    session_info: SessionSummary
    
    # 采集进度
    collection_progress: Dict[str, ProgressInfo] = Field(default_factory=dict)
    
    # 采集数据
    collected_data: CollectedData = Field(default_factory=CollectedData)
    
    # 原始对话文件路径
    raw_conversations_path: str = Field(default="", description="原始对话记录文件路径")
    
    # 待处理问题
    pending_questions: List[str] = Field(default_factory=list)
    
    # 给下游的提示
    notes_for_agent_b: List[str] = Field(default_factory=list)
```

### 4.9 AgentResponse（Agent响应）

```python
# src/models/agent_response.py
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional


class AgentResponse(BaseModel):
    """
    Agent响应 - 单轮对话的响应结构
    
    职责：
    - 封装Agent的响应信息
    - 包含状态更新
    
    使用场景：
    - ConversationOrchestrator.process_turn() 的返回值
    - 返回给上层调用者
    """
    
    message: str = Field(..., description="Agent回复消息")
    state_update: Dict[str, Any] = Field(default_factory=dict, description="状态更新摘要")
    should_pause: bool = Field(default=False, description="是否应该暂停")
    pause_reason: Optional[str] = Field(default=None, description="暂停原因")
    handoff_triggered: bool = Field(default=False, description="是否触发交接")
```

---

## 五、开发要求

### 5.1 代码规范

```python
# 1. 使用 Pydantic v2 进行数据验证
from pydantic import BaseModel, Field

# 2. 所有模型继承 BaseModel
class MyModel(BaseModel):
    pass

# 3. 使用 Field 添加描述和验证
name: str = Field(..., description="名称", min_length=1, max_length=100)

# 4. 使用枚举类型约束取值范围
from enums import StateType
state: StateType = Field(default=StateType.INIT)

# 5. 提供工厂函数创建默认值
coverage: Dict[str, float] = Field(default_factory=lambda: {"childhood": 0.0})

# 6. 提供 @classmethod 工厂方法
@classmethod
def empty(cls) -> "MyModel":
    return cls(...)
```

### 5.2 单元测试要求

```python
# tests/test_session_state.py
import pytest
from models import SessionState, ConversationTurn
from enums import StateType, PhaseType

class TestSessionState:
    def test_create_session(self):
        """测试创建会话"""
        session = SessionState(session_id="test-001")
        assert session.session_id == "test-001"
        assert session.current_state == StateType.INIT
    
    def test_add_turn(self):
        """测试添加对话轮次"""
        session = SessionState(session_id="test-001")
        turn = ConversationTurn(turn_id=1, user_input="测试输入")
        session.add_turn(turn)
        
        assert session.turn_count == 1
        assert len(session.conversation_history) == 1
    
    def test_update_coverage(self):
        """测试更新覆盖率"""
        session = SessionState(session_id="test-001")
        session.update_coverage(PhaseType.CHILDHOOD, 0.5)
        
        assert session.coverage[PhaseType.CHILDHOOD] == 0.5
    
    def test_pending_questions(self):
        """测试待追问问题"""
        session = SessionState(session_id="test-001")
        session.push_pending_question("问题1")
        session.push_pending_question("问题2")
        
        assert session.has_pending_questions()
        assert session.pop_pending_question() == "问题1"
        assert session.pop_pending_question() == "问题2"
    
    def test_to_summary(self):
        """测试生成摘要"""
        session = SessionState(session_id="test-001")
        summary = session.to_summary()
        
        assert "session_id" in summary
        assert "turn_count" in summary
```

### 5.3 验收标准

- [ ] 所有数据对象实现完成
- [ ] 所有枚举类型定义完成
- [ ] 单元测试覆盖率 > 80%
- [ ] 所有测试通过
- [ ] 代码通过 mypy 类型检查
- [ ] 代码通过 ruff/pylint 检查

---

## 六、参考资源

### 6.1 相关文档

- [问答引导层Agent-详细设计.md](../问答引导层Agent-详细设计.md)
- [问答引导层Agent-系统架构设计.md](../问答引导层Agent-系统架构设计.md)

### 6.2 技术文档

- [Pydantic v2 文档](https://docs.pydantic.dev/latest/)
- [Python dataclasses 文档](https://docs.python.org/3/library/dataclasses.html)
- [Python enum 文档](https://docs.python.org/3/library/enum.html)

---

## 七、注意事项

1. **类型安全**：使用 Pydantic 确保类型安全，避免运行时类型错误
2. **不可变性**：关键属性考虑使用 frozen=True 或 @property
3. **序列化**：所有模型必须支持 JSON 序列化（model_dump_json）
4. **文档完整**：每个字段必须有 description
5. **默认值合理**：默认值必须符合业务逻辑，避免 None 滥用
