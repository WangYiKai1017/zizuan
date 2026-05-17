"""传记写作 Agent 状态模型"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from src.models.biography_models import AgentStatus, ChapterTask


class WritingAgentState(BaseModel):
    """传记写作 Agent 的 LangGraph 状态"""

    # 配置
    user_id: str = ""
    kb_path: str = ""
    biography_path: str = ""

    # 任务队列
    chapters_to_write: list[ChapterTask] = Field(default_factory=list)
    current_chapter: Optional[ChapterTask] = None
    current_chapter_index: int = 0

    # 当前写作的工作数据
    source_content: str = ""
    character_profiles: str = ""
    timeline_context: str = ""

    # 写作输出
    draft_content: str = ""  # 当前章节的初稿
    reviewed_content: str = ""  # 审阅后的内容

    # 完成追踪
    completed_chapters: list[str] = Field(default_factory=list)  # 已完成的 chapter_ids

    # 状态控制
    status: AgentStatus = AgentStatus.RUNNING
    error_message: str = ""
