from enum import Enum
from typing import List, Dict, Optional, Union
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class TaskStatus(str, Enum):
    """整理任务状态枚举"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class OrganizerTask(BaseModel):
    """
    单个整理任务

    职责：
    - 描述一个可执行的整理步骤
    - 跟踪执行状态与结果

    使用场景：
    - KBOrganizerAgent 的任务板条目
    - Plan-Execute 循环中的执行单元
    """

    task_id: str = Field(..., description="任务唯一标识")
    task_type: str = Field(
        ...,
        description=(
            "任务类型: setup_workspace / read_documents / "
            "merge_duplicates / check_conflicts / "
            "detect_contradictions / repair_links / "
            "prune_conversations / finalize_swap"
        ),
    )
    description: str = Field(..., description="任务描述")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="任务状态")
    result: Optional[str] = Field(default=None, description="执行结果摘要")
    error: Optional[str] = Field(default=None, description="错误信息")
    affected_files: List[str] = Field(default_factory=list, description="受影响的文件列表")
    retry_count: int = Field(default=0, description="重试次数")


class ConflictItem(BaseModel):
    """
    矛盾问题记录

    职责：
    - 记录文档间发现的事实矛盾
    - 跟踪解决状态与方案

    使用场景：
    - 矛盾检测阶段产出
    - 手动/自动修复的输入
    """

    conflict_id: str = Field(..., description="矛盾唯一标识")
    conflict_type: str = Field(
        ...,
        description="矛盾类型: time / location / relationship / causal",
    )
    description: str = Field(..., description="矛盾描述（标准化格式）")
    source_files: List[str] = Field(..., description="涉及的文档路径")
    resolved: bool = Field(default=False, description="是否已解决")
    resolution: Optional[str] = Field(default=None, description="解决方案描述")
    evidence: Optional[str] = Field(default=None, description="支撑解决的证据来源")

    @field_validator("evidence", mode="before")
    @classmethod
    def normalize_evidence(cls, v):
        if isinstance(v, list):
            return "\n".join(str(item) for item in v)
        return v


class MergeRecord(BaseModel):
    """
    合并记录

    职责：
    - 记录一次文档合并操作的完整信息
    - 确保合并可追溯、可回滚

    使用场景：
    - 重复文档合并后的审计记录
    - 链接修复的依据
    """

    merge_id: str = Field(..., description="合并记录唯一标识")
    source_files: List[str] = Field(..., description="被合并的源文件列表")
    target_file: str = Field(..., description="合并后的目标文件")
    merge_reason: str = Field(..., description="合并原因")
    preserved_details: List[str] = Field(default_factory=list, description="保留的关键细节清单")


# 任务最大重试次数
MAX_TASK_RETRIES = 2


class KBOrganizerState(BaseModel):
    """
    知识库整理 Agent 全局状态

    职责：
    - 维护整理流程的完整运行上下文
    - 提供任务调度与状态查询接口

    使用场景：
    - KBOrganizerAgent 的 Plan-Execute 循环
    - 各整理步骤间的状态传递
    """

    # 基本信息
    user_id: str = Field(..., description="用户标识")
    source_path: str = Field(..., description="原始知识库路径")
    working_path: str = Field(..., description="工作副本路径")

    # 任务板
    task_plan: List[OrganizerTask] = Field(default_factory=list, description="任务计划列表")
    current_task_index: int = Field(default=0, description="当前任务索引")

    # 文档清单
    all_files: Dict[str, List[str]] = Field(
        default_factory=dict, description="分类文档清单: category -> [file_paths]"
    )

    # 合并记录
    merge_records: List[MergeRecord] = Field(default_factory=list, description="合并操作记录")

    # 矛盾管理
    conflict_items: List[ConflictItem] = Field(default_factory=list, description="矛盾问题列表")

    # 链接映射（旧路径 -> 新路径）
    link_redirect_map: Dict[str, str] = Field(
        default_factory=dict, description="链接重定向映射: 旧路径 -> 新路径"
    )

    # 运行元数据
    started_at: Optional[datetime] = Field(default=None, description="开始时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")
    iteration_count: int = Field(default=0, description="迭代次数")

    # 文档内容索引
    document_contents: Dict[str, str] = Field(
        default_factory=dict, description="文档内容缓存: file_path -> content"
    )

    def get_current_task(self) -> Optional[OrganizerTask]:
        """获取当前待执行任务（第一个 PENDING 状态的任务）"""
        pending = [t for t in self.task_plan if t.status == TaskStatus.PENDING]
        return pending[0] if pending else None

    def all_tasks_done(self) -> bool:
        """检查是否所有任务已完成、跳过或达到最大重试次数"""
        for t in self.task_plan:
            if t.status == TaskStatus.FAILED:
                if t.retry_count < MAX_TASK_RETRIES:
                    # Reset to PENDING for retry
                    t.retry_count += 1
                    t.status = TaskStatus.PENDING
                    t.error = None
                    return False
                # Exhausted retries — treat as terminal
                continue
            if t.status not in (TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.FAILED):
                return False
        return True

    def get_active_conflicts(self) -> List[ConflictItem]:
        """获取未解决的矛盾列表"""
        return [c for c in self.conflict_items if not c.resolved]

    def register_merge(
        self,
        sources: List[str],
        target: str,
        reason: str,
        details: List[str],
    ) -> None:
        """注册一次合并操作，同时更新链接映射

        Args:
            sources: 被合并的源文件路径列表
            target: 合并后的目标文件路径
            reason: 合并原因说明
            details: 保留的关键细节清单
        """
        record = MergeRecord(
            merge_id=f"merge_{len(self.merge_records) + 1:03d}",
            source_files=sources,
            target_file=target,
            merge_reason=reason,
            preserved_details=details,
        )
        self.merge_records.append(record)
        for src in sources:
            if src != target:
                self.link_redirect_map[src] = target
