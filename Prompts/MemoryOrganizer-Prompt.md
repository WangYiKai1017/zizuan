# MemoryOrganizer 动态 Prompt 模板

> 模板名称：`memory_organization`  
> 职责：从采访内容中整理关键信息，按时间线/事件/人物三维度结构化  
> 版本：v1.0  
> 日期：2026-04-22

---

## 一、Prompt 模板结构

```
## 系统角色

你是一位专业的信息整理专家，负责从老人采访对话中提取、整理、结构化关键信息。你需要将原始的对话内容转化为可供长期存储的知识条目。

## 任务说明

分析提供的采访对话内容，从三个维度整理关键信息：
1. **时间线维度**：建立或更新人生时间线节点
2. **事件维度**：提取完整的事件记录
3. **人物维度**：识别并完善人物画像

## 特殊场景处理

### 1. 主人公场景
- 需包含主人公详细信息（姓名、年龄、职业、家庭状况等）
- 主人公信息文档与index.md放置于同一目录（根目录）
- 严格按照知识库组织架构：
  - 事件：按人生阶段分类（childhood/youth/young_adult/middle_age/elderly）
  - 人物：按关系分类（family/friends/colleagues/others）
  - 时间线：按人生阶段分类

### 2. 对话记录场景
- 创建专用文档存储历史对话记录
- 对话记录文档命名格式：`conversation_YYYY-MM-DD_HH-MM-SS.md`
- 存储路径：`/Users/yikaiwang/Documents/trae_projects/zizhuan/knowledge_base/conversations/`
- 记录格式：包含时间戳、角色和内容

## 输入信息

### 采访对话内容
{conversation_content}

### 已有时间线记录
{existing_timeline}

### 已有人物索引
{existing_people}

### 当前人生阶段
{current_phase}

### 主人公基础信息（如果有）
{protagonist_basic_info}

## 整理原则

### 1. 时间线整理原则
- **精确定位**：尽可能确定事件发生的时间点或时间段
- **阶段归属**：将事件归入对应的人生阶段（童年/青少年/青年/中年/老年）
- **时间推断**：若没有明确时间，根据上下文推断（如"那时候我刚工作"→青年早期）
- **模糊处理**：实在无法确定时间的，标记为"时间不详"

### 2. 事件整理原则
- **完整性**：每个事件应包含：时间、地点、人物、起因、经过、结果
- **重要性**：区分核心事件（人生转折点）和一般事件（日常回忆）
- **关联性**：标注事件之间的关联关系
- **情感标记**：记录用户对事件的主观评价和情感

### 3. 人物整理原则
- **身份明确**：姓名、与用户的关系、出现的时间段
- **特征描写**：外貌、性格、职业等具体描述
- **关系网络**：与其他人物的关系
- **影响标记**：对用户人生的影响程度

### 4. 画像记忆整理原则
- **基础信息**：主人公的关键人生节点
- **性格特征**：从叙述中推断的性格特点
- **价值观**：体现的人生观、价值观
- **关系图谱**：人物关系的结构化呈现

## 输出格式

请严格按照以下 JSON Schema 输出：

```json
{
  "timeline_updates": [
    {
      "time_point": "string (时间点，如'1965年'或'童年时期')",
      "time_type": "string (exact|approximate|period|unknown)",
      "life_phase": "string (childhood|youth|young_adult|middle_age|elderly)",
      "event_reference": "string (关联的事件ID)",
      "significance": "string (时间节点意义)"
    }
  ],
  
  "events": [
    {
      "event_id": "string (唯一ID，格式：evt_时间_序号，如evt_1965_001)",
      "title": "string (事件标题，简洁概括)",
      "time": "string (发生时间)",
      "location": "string (地点，若未知填null)",
      "event_type": "string (birth|family|education|career|marriage|children|achievement|difficulty|migration|other)",
      "importance": "string (core|important|normal)",
      "description": "string (详细描述)",
      "participants": ["string (参与人物ID)"],
      "emotions": ["string (用户情感标签)"],
      "user_evaluation": "string (用户主观评价)",
      "related_events": ["string (关联事件ID)"],
      "source_turns": ["int (来源对话轮次)"],
      "confidence": "number (0-1，信息完整度)"
    }
  ],
  
  "people": [
    {
      "person_id": "string (唯一ID，格式：ppl_姓名拼音_序号)",
      "name": "string (姓名)",
      "relation": "string (与用户关系)",
      "relation_type": "string (family|friend|colleague|neighbor|teacher|student|other)",
      "first_appear_time": "string (首次出现时间)",
      "description": "string (人物描述)",
      "appearance": "string (外貌特征，可选)",
      "personality": "string (性格特点，可选)",
      "occupation": "string (职业，可选)",
      "key_quotes": ["string (用户提到该人物的原话)"],
      "relationships": [
        {
          "related_person_id": "string",
          "relationship": "string (关系描述)"
        }
      ],
      "influence_level": "string (high|medium|low)",
      "source_turns": ["int"]
    }
  ],
  
  "profile_updates": {
    "protagonist": {
      "birth_year": "string (出生年份，若能推断)",
      "birth_place": "string (出生地)",
      "key_life_events": ["string (人生关键节点)"],
      "personality_traits": ["string (性格特点推断)"],
      "values_hints": ["string (价值观线索)"]
    },
    "relationship_network": [
      {
        "person1_id": "string",
        "person2_id": "string", 
        "relationship": "string",
        "evidence": "string (关系证据)"
      }
    ]
  },
  
  "storage_suggestions": {
    "timeline_file": "string (建议更新的时间线文件路径)",
    "event_files": [
      {
        "event_id": "string",
        "suggested_path": "string (建议的存储路径)"
      }
    ],
    "people_files": [
      {
        "person_id": "string",
        "suggested_path": "string (建议的存储路径)"
      }
    ],
    "conversation_file": "string (建议保存的对话记录文件路径)"
  },
  
  "processing_summary": {
    "total_events_extracted": "int",
    "total_people_identified": "int",
    "timeline_nodes_added": "int",
    "confidence_avg": "number",
    "notes": "string (整理备注)"
  }
}
```

## 注意事项

1. **避免重复**：与已有时间线和人物索引对比，避免重复创建
2. **增量更新**：如果人物已存在，只更新新信息，不要覆盖已有内容
3. **ID规范**：使用统一的ID格式，便于后续查询和关联
4. **置信度**：对于推断的信息，标注较低的置信度
5. **来源追溯**：记录每条信息的来源对话轮次，便于核查
```

---

## 二、动态变量说明

| 变量名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| `{conversation_content}` | string | 多轮对话格式化 | 采访对话内容 |
| `{existing_timeline}` | string | MemoryRepository | 已有时间线记录 |
| `{existing_people}` | string | MemoryRepository | 已有人物索引 |
| `{current_phase}` | string | SessionState | 当前采访的人生阶段 |

### 变量格式化规则

#### conversation_content

```python
def _format_conversation_content(self, turns: List[ConversationTurn]) -> str:
        """格式化对话内容"""
        lines = []
        for i, turn in enumerate(turns, 1):
            lines.append(f"### 第 {i} 轮")
            lines.append(f"时间：{turn.timestamp.strftime('%H:%M:%S')}")
            lines.append(f"用户：{turn.user_input}")
            if turn.agent_response:
                lines.append(f"助手：{turn.agent_response}")
            lines.append("")
        return "\n".join(lines)
    
    def _format_protagonist_info(self) -> str:
        """格式化主人公基础信息"""
        protagonist = self.repository.get_person("protagonist")
        if protagonist:
            info = []
            info.append(f"姓名：{protagonist.name}")
            info.append(f"年龄：{protagonist.age}")
            info.append(f"职业：{protagonist.occupation}")
            info.append(f"家庭状况：{protagonist.family_status}")
            info.append(f"居住情况：{protagonist.living_arrangement}")
            return "\n".join(info)
        return "（暂无主人公信息）"
```

#### existing_timeline

```python
def _format_existing_timeline(self, repository: MemoryRepository) -> str:
    """格式化已有时间线"""
    events = repository.get_all_events()
    if not events:
        return "（暂无时间线记录）"
    
    lines = ["已有时间线节点："]
    # 按时间排序
    sorted_events = sorted(events, key=lambda e: e.time or "")
    for event in sorted_events[:20]:  # 限制数量
        lines.append(f"- {event.time}: {event.title}")
    return "\n".join(lines)
```

#### existing_people

```python
def _format_existing_people(self, repository: MemoryRepository) -> str:
    """格式化已有人物索引"""
    people = repository.get_all_people()
    if not people:
        return "（暂无人物记录）"
    
    lines = ["已有人物："]
    for person in people:
        lines.append(f"- {person.name} ({person.role})")
    return "\n".join(lines)
```

#### current_phase

```python
PHASE_LABELS = {
    PhaseType.CHILDHOOD: "童年时期（0-12岁）",
    PhaseType.YOUTH: "青少年时期（12-18岁）",
    PhaseType.YOUNG_ADULT: "青年时期（18-35岁）",
    PhaseType.MIDDLE_AGE: "中年时期（35-60岁）",
    PhaseType.ELDERLY: "老年时期（60岁以后）",
}
```

---

## 三、调用方式

### MemoryManager 调用代码

```python
# src/services/memory_manager.py
from services.llm_service import LLMService, get_llm_service

class MemoryManager:
    def __init__(
        self,
        repository: MemoryRepository,
        llm_service: LLMService = None,
    ):
        self.repository = repository
        self.llm_service = llm_service or get_llm_service()
    
    async def organize_and_save(
        self,
        turns: List[ConversationTurn],
        current_phase: PhaseType,
    ) -> OrganizedMemory:
        """
        整理并保存记忆
        
        Args:
            turns: 对话轮次列表
            current_phase: 当前人生阶段
            
        Returns:
            OrganizedMemory: 整理后的结构化记忆
        """
        # 1. 格式化输入变量
        variables = {
            "conversation_content": self._format_conversation_content(turns),
            "existing_timeline": self._format_existing_timeline(self.repository),
            "existing_people": self._format_existing_people(self.repository),
            "current_phase": PHASE_LABELS.get(current_phase, str(current_phase)),
            "protagonist_basic_info": self._format_protagonist_info(),
        }
        
        # 2. 调用 LLM 整理
        result, raw = await self.llm_service.invoke_structured(
            template_name="memory_organization",
            variables=variables,
            output_model=OrganizedMemory,
        )
        
        if result is None:
            logger.error(f"Memory organization failed: {raw.error}")
            return OrganizedMemory.empty()
        
        # 3. 按整理结果存储
        await self._apply_organized_memory(result)
        
        return result
    
    async def _apply_organized_memory(self, memory: OrganizedMemory) -> Dict[str, str]:
        """应用整理结果到存储"""
        results = {}
        
        # 并行保存事件和人物
        tasks = []
        
        # 保存事件
        for event in memory.events:
            event_info = self._convert_to_event_info(event)
            tasks.append(self._save_event_with_timeline(event_info, memory.timeline_updates))
        
        # 保存人物
        for person in memory.people:
            person_info = self._convert_to_person_info(person)
            tasks.append(self.repository.save_person(person_info))
        
        # 更新画像
        self._update_profile_from_memory(memory.profile_updates)
        
        if tasks:
            paths = await asyncio.gather(*tasks, return_exceptions=True)
            results["files_created"] = [p for p in paths if isinstance(p, str)]
        
        return results
```

---

## 四、输出数据结构

### OrganizedMemory (Pydantic Model)

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

class TimeType(str, Enum):
    EXACT = "exact"           # 精确时间
    APPROXIMATE = "approximate"  # 大约时间
    PERIOD = "period"         # 时间段
    UNKNOWN = "unknown"       # 时间不详

class EventType(str, Enum):
    BIRTH = "birth"
    FAMILY = "family"
    EDUCATION = "education"
    CAREER = "career"
    MARRIAGE = "marriage"
    CHILDREN = "children"
    ACHIEVEMENT = "achievement"
    DIFFICULTY = "difficulty"
    MIGRATION = "migration"
    OTHER = "other"

class Importance(str, Enum):
    CORE = "core"        # 核心事件（人生转折点）
    IMPORTANT = "important"
    NORMAL = "normal"

class RelationType(str, Enum):
    FAMILY = "family"
    FRIEND = "friend"
    COLLEAGUE = "colleague"
    NEIGHBOR = "neighbor"
    TEACHER = "teacher"
    STUDENT = "student"
    OTHER = "other"

class InfluenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

# ========== 时间线更新 ==========

class TimelineUpdate(BaseModel):
    time_point: str
    time_type: TimeType
    life_phase: str
    event_reference: Optional[str] = None
    significance: Optional[str] = None

# ========== 事件 ==========

class EventExtract(BaseModel):
    event_id: str
    title: str
    time: Optional[str] = None
    location: Optional[str] = None
    event_type: EventType
    importance: Importance
    description: str
    participants: List[str] = Field(default_factory=list)
    emotions: List[str] = Field(default_factory=list)
    user_evaluation: Optional[str] = None
    related_events: List[str] = Field(default_factory=list)
    source_turns: List[int] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)

# ========== 人物 ==========

class PersonRelationship(BaseModel):
    related_person_id: str
    relationship: str

class PersonExtract(BaseModel):
    person_id: str
    name: str
    relation: str
    relation_type: RelationType
    first_appear_time: Optional[str] = None
    description: str
    appearance: Optional[str] = None
    personality: Optional[str] = None
    occupation: Optional[str] = None
    key_quotes: List[str] = Field(default_factory=list)
    relationships: List[PersonRelationship] = Field(default_factory=list)
    influence_level: InfluenceLevel = InfluenceLevel.MEDIUM
    source_turns: List[int] = Field(default_factory=list)

# ========== 画像更新 ==========

class ProtagonistUpdate(BaseModel):
    birth_year: Optional[str] = None
    birth_place: Optional[str] = None
    key_life_events: List[str] = Field(default_factory=list)
    personality_traits: List[str] = Field(default_factory=list)
    values_hints: List[str] = Field(default_factory=list)

class RelationshipEdge(BaseModel):
    person1_id: str
    person2_id: str
    relationship: str
    evidence: Optional[str] = None

class ProfileUpdates(BaseModel):
    protagonist: Optional[ProtagonistUpdate] = None
    relationship_network: List[RelationshipEdge] = Field(default_factory=list)

# ========== 存储建议 ==========

class FileSuggestion(BaseModel):
    event_id: Optional[str] = None
    person_id: Optional[str] = None
    suggested_path: str

class StorageSuggestions(BaseModel):
    timeline_file: Optional[str] = None
    event_files: List[FileSuggestion] = Field(default_factory=list)
    people_files: List[FileSuggestion] = Field(default_factory=list)

# ========== 处理摘要 ==========

class ProcessingSummary(BaseModel):
    total_events_extracted: int = 0
    total_people_identified: int = 0
    timeline_nodes_added: int = 0
    confidence_avg: float = 0.0
    notes: Optional[str] = None

# ========== 完整输出 ==========

class OrganizedMemory(BaseModel):
    timeline_updates: List[TimelineUpdate] = Field(default_factory=list)
    events: List[EventExtract] = Field(default_factory=list)
    people: List[PersonExtract] = Field(default_factory=list)
    profile_updates: Optional[ProfileUpdates] = None
    storage_suggestions: Optional[StorageSuggestions] = None
    processing_summary: Optional[ProcessingSummary] = None
    
    @classmethod
    def empty(cls) -> "OrganizedMemory":
        return cls()
```

---

## 五、存储路径规则

### 事件存储

```
knowledge_base/
├── events/
│   ├── childhood/       # 童年事件
│   │   ├── 出生.md
│   │   └── 童年记忆-小院枣树.md
│   ├── youth/           # 青少年事件
│   ├── young_adult/     # 青年事件
│   ├── middle_age/      # 中年事件
│   └── elderly/         # 老年事件
```

### 人物存储

```
knowledge_base/
├── people/
│   ├── family/          # 家人
│   │   ├── 父亲.md
│   │   └── 母亲.md
│   ├── friends/         # 朋友
│   ├── colleagues/      # 同事
│   └── others/          # 其他
```

### 时间线存储

```
knowledge_base/
├── timeline/
│   ├── life-events.md   # 总时间线
│   ├── childhood.md     # 童年时间线
│   └── youth.md         # 青少年时间线
```

---

## 六、Markdown 文件模板

### 事件文件模板

```markdown
# {title}

> 事件ID: {event_id}  
> 时间: {time}  
> 类型: {event_type}  
> 重要程度: {importance}

## 事件描述

{description}

## 参与人物

{participants 列表，带 Wiki 链接}

## 地点

{location}

## 用户评价

{user_evaluation}

## 相关事件

{related_events 列表，带 Wiki 链接}

## 来源对话

{source_turns 引用}

---
*置信度: {confidence}*
```

### 人物文件模板

```markdown
# {name}

> 人物ID: {person_id}  
> 关系: {relation}  
> 首次出现: {first_appear_time}

## 人物描述

{description}

## 外貌特征

{appearance}

## 性格特点

{personality}

## 职业

{occupation}

## 关系网络

{relationships 列表}

## 用户原话

{key_quotes 列表}

---
*影响程度: {influence_level}*
```

---

## 七、示例

### 输入示例

```
采访对话内容：
### 第 1 轮
时间：14:30:15
用户：我记得小时候住在一个小院子里。
助手：那是怎样的院子呢？

### 第 2 轮
时间：14:30:45
用户：院子不大，但种了一棵枣树。每到秋天，我们兄弟姐妹就盼着枣子熟。

### 第 3 轮
时间：14:31:20
用户：那棵枣树很老了，听父亲说是他小时候种的。父亲常在树下给我们讲故事。

已有时间线记录：
（暂无时间线记录）

已有人物：          
（暂无人物记录）

当前人生阶段：童年时期（0-12岁）
```

### 输出示例

```json
{
  "timeline_updates": [
    {
      "time_point": "童年时期",
      "time_type": "period",
      "life_phase": "childhood",
      "event_reference": "evt_childhood_001",
      "significance": "家庭生活记忆的起点"
    }
  ],
  
  "events": [
    {
      "event_id": "evt_childhood_001",
      "title": "童年小院生活",
      "time": "童年时期",
      "location": "家中院子",
      "event_type": "family",
      "importance": "normal",
      "description": "用户童年时期住在一个有小院子的家里，院子里有一棵老枣树，是父亲小时候种的。秋天时兄弟姐妹一起盼望枣子成熟，父亲常在树下讲故事。",
      "participants": ["ppl_father_001", "ppl_siblings_001"],
      "emotions": ["怀旧", "温馨"],
      "user_evaluation": "温馨的家庭回忆，枣树是重要意象",
      "related_events": [],
      "source_turns": [1, 2, 3],
      "confidence": 0.9
    }
  ],
  
  "people": [
    {
      "person_id": "ppl_father_001",
      "name": "父亲",
      "relation": "父亲",
      "relation_type": "family",
      "first_appear_time": "童年时期",
      "description": "用户的父亲，枣树的种植者，常在树下给孩子讲故事",
      "appearance": null,
      "personality": "关爱孩子，喜欢讲故事",
      "occupation": null,
      "key_quotes": ["那棵枣树很老了，听父亲说是他小时候种的", "父亲常在树下给我们讲故事"],
      "relationships": [],
      "influence_level": "high",
      "source_turns": [3]
    },
    {
      "person_id": "ppl_siblings_001",
      "name": "兄弟姐妹",
      "relation": "兄弟姐妹",
      "relation_type": "family",
      "first_appear_time": "童年时期",
      "description": "与用户一起盼望枣子成熟的兄弟姐妹",
      "key_quotes": ["我们兄弟姐妹就盼着枣子熟"],
      "relationships": [],
      "influence_level": "medium",
      "source_turns": [2]
    }
  ],
  
  "profile_updates": {
    "protagonist": {
      "key_life_events": ["童年小院生活"],
      "personality_traits": ["怀旧"],
      "values_hints": ["重视家庭"]
    },
    "relationship_network": [
      {
        "person1_id": "protagonist",
        "person2_id": "ppl_father_001",
        "relationship": "父子",
        "evidence": "父亲常在树下给我们讲故事"
      }
    ]
  },
  
  "storage_suggestions": {
    "timeline_file": "timeline/childhood.md",
    "event_files": [
      {
        "event_id": "evt_childhood_001",
        "suggested_path": "events/childhood/童年小院生活.md"
      }
    ],
    "people_files": [
      {
        "person_id": "ppl_father_001",
        "suggested_path": "people/family/父亲.md"
      },
      {
        "person_id": "ppl_siblings_001",
        "suggested_path": "people/family/兄弟姐妹.md"
      }
    ]
  },
  
  "processing_summary": {
    "total_events_extracted": 1,
    "total_people_identified": 2,
    "timeline_nodes_added": 1,
    "confidence_avg": 0.9,
    "notes": "高质量的童年回忆，信息完整，情感清晰。枣树是重要意象，后续可以深入挖掘父亲的故事。"
  }
}
```

---

## 八、重要规则

### user.md 文档
- `user.md` 是被采访对象（主人公）的个人档案文档
- 所有与被采访对象本人相关的基本信息（姓名、年龄、职业、家庭情况等）应记录在此文档中
- 在整理记忆时，如果发现了新的个人信息，请在输出中标注需要更新 user.md

### 路径限制
- 严禁对 /biography 路径下的内容进行任何操作（读取、写入、修改）
- /biography 路径属于传记写作模块，不在记忆整理的工作范围内
