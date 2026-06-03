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


# 时间线更新
class TimelineUpdate(BaseModel):
    time_point: str
    time_type: TimeType
    life_phase: str
    event_reference: Optional[str] = None
    significance: Optional[str] = None


# 事件提取
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


# 人物关系
class PersonRelationship(BaseModel):
    related_person_id: str
    relationship: str


# 人物提取
class PersonExtract(BaseModel):
    person_id: str
    name: str
    relation: str
    relation_type: RelationType
    first_appear_time: Optional[str] = None
    description: str
    appearance: Optional[str] = None
    personality: Optional[Any] = None
    occupation: Optional[str] = None
    key_quotes: List[str] = Field(default_factory=list)
    relationships: List[PersonRelationship] = Field(default_factory=list)
    influence_level: InfluenceLevel = InfluenceLevel.MEDIUM
    source_turns: List[int] = Field(default_factory=list)


# 画像更新
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


# 存储建议
class FileSuggestion(BaseModel):
    event_id: Optional[str] = None
    person_id: Optional[str] = None
    suggested_path: str


class StorageSuggestions(BaseModel):
    timeline_file: Optional[Any] = None
    event_files: List[FileSuggestion] = Field(default_factory=list)
    people_files: List[FileSuggestion] = Field(default_factory=list)


# 处理摘要
class ProcessingSummary(BaseModel):
    total_events_extracted: int = 0
    total_people_identified: int = 0
    timeline_nodes_added: int = 0
    confidence_avg: float = 0.0
    notes: Optional[str] = None


# 完整输出
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
