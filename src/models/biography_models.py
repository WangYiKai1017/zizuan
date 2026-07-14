"""传记写作系统共享数据模型

定义 OutlineAgent 和 WritingAgent 共用的 Pydantic 模型。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ChapterStatus(str, Enum):
    """章节状态枚举"""

    DRAFT = "draft"  # 新生成，待用户确认
    CONFIRMED = "confirmed"  # 用户已确认，待写作
    WRITTEN = "written"  # 已完成写作
    OUTDATED = "outdated"  # 源材料变更，需更新


class AgentStatus(str, Enum):
    """Agent 运行状态"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class LifeStage(str, Enum):
    """人生阶段"""

    CHILDHOOD = "childhood"
    YOUTH = "youth"
    MIDDLE_AGE = "middle_age"
    ELDERLY = "elderly"


class ChapterEntry(BaseModel):
    """章节条目 - outline.yaml 中的每一章"""

    id: str = Field(..., description="章节唯一标识，如 ch01")
    title: str = Field(..., description="章节标题")
    life_stage: str = Field(..., description="所属人生阶段")
    theme: str = Field(..., description="章节主题")
    status: ChapterStatus = Field(default=ChapterStatus.DRAFT)
    source_materials: list[str] = Field(
        default_factory=list, description="引用的知识库文件路径列表"
    )
    summary: str = Field(default="", description="章节内容摘要")
    confirmed_at: Optional[datetime] = Field(default=None)
    written_at: Optional[datetime] = Field(default=None)


class OutlineDocument(BaseModel):
    """大纲文档 - outline.yaml 的完整结构"""

    title: str = Field(default="我的人生故事", description="传记标题")
    author: str = Field(default="", description="传主姓名")
    style: str = Field(default="first_person_oral", description="写作风格")
    version: int = Field(default=1, description="大纲版本号")
    last_updated: datetime = Field(default_factory=datetime.now)
    chapters: list[ChapterEntry] = Field(default_factory=list)


class EventSummary(BaseModel):
    """事件摘要 - 从 KB events/ 提取"""

    file_path: str = Field(..., description="相对文件路径")
    title: str = Field(default="")
    life_stage: str = Field(default="")
    event_type: str = Field(default="")
    description: str = Field(default="")
    people: list[str] = Field(default_factory=list)
    emotion_tags: list[str] = Field(default_factory=list)


class PersonSummary(BaseModel):
    """人物摘要 - 从 KB people/ 提取"""

    file_path: str = Field(..., description="相对文件路径")
    name: str = Field(default="")
    relationship: str = Field(default="")
    description: str = Field(default="")
    influence: str = Field(default="")
    quotes: list[str] = Field(default_factory=list)


class TimelineEntry(BaseModel):
    """时间线条目 - 从 KB timeline/ 提取"""

    life_stage: str = Field(default="")
    event_title: str = Field(default="")
    event_type: str = Field(default="")
    detail_link: str = Field(default="")


class OutlineChange(BaseModel):
    """大纲变更记录"""

    action: str = Field(
        ...,
        description="add / update / mark_outdated / remove_duplicate",
    )
    chapter_id: str = Field(default="")
    chapter_entry: Optional[ChapterEntry] = Field(default=None)
    reason: str = Field(default="")


class ChapterTask(BaseModel):
    """写作任务 - WritingAgent 的任务队列项"""

    chapter_id: str
    chapter_title: str
    life_stage: str
    theme: str
    source_materials: list[str] = Field(default_factory=list)
    summary: str = Field(default="")


class BiographyState(BaseModel):
    """增量处理状态 - .state.json 的结构"""

    last_outline_run: Optional[datetime] = None
    kb_content_hash: str = ""
    processed_files: list[str] = Field(default_factory=list)
    chapter_versions: dict[str, int] = Field(default_factory=dict)
