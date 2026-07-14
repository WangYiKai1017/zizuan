"""大纲规划 Agent 状态模型"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from src.models.biography_models import (
    AgentStatus,
    ChapterEntry,
    EventSummary,
    OutlineChange,
    OutlineDocument,
    PersonSummary,
    TimelineEntry,
)


class OutlineAgentState(BaseModel):
    """大纲规划 Agent 的 LangGraph 状态"""

    # 配置
    user_id: str = ""
    kb_path: str = ""
    biography_path: str = ""

    # 扫描阶段输出
    events: list[EventSummary] = Field(default_factory=list)
    people: list[PersonSummary] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    raw_materials_text: str = ""  # 格式化后的材料文本(给LLM用)
    has_changes: bool = True  # 是否检测到新材料
    needs_outline_repair: bool = False  # 已有大纲包含可确定修复的重复章节
    changed_files: list[str] = Field(default_factory=list)

    # 分析阶段输出
    analysis_result: str = ""  # LLM分析结果(JSON string)

    # 大纲生成阶段
    current_outline: Optional[OutlineDocument] = None  # 已有大纲
    proposed_chapters: list[ChapterEntry] = Field(default_factory=list)

    # 最终输出
    final_outline: Optional[OutlineDocument] = None
    changes_made: list[OutlineChange] = Field(default_factory=list)

    # 状态控制
    status: AgentStatus = AgentStatus.RUNNING
    error_message: str = ""
