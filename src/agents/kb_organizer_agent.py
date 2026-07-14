"""知识库整理 Agent

采用 Plan-Execute (ReAct) 模式，通过 LangGraph 编排执行知识库整理任务。
"""

import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from src.models.kb_organizer_state import (
    KBOrganizerState,
    OrganizerTask,
    TaskStatus,
)
from src.services.kb_organization_service import KBOrganizationService
from src.services.llm_service import LLMService
from src.services.observability import observe_step
from src.storage.file_operations import FileOperations

logger = logging.getLogger(__name__)

# 固定 8 步任务定义
_TASK_DEFINITIONS = [
    ("task_01", "setup_workspace", "创建工作副本并扫描文件清单"),
    ("task_02", "read_documents", "阅读所有文档并建立内存索引"),
    ("task_03", "merge_duplicates", "检测并合并重复/相似文档"),
    ("task_04", "check_conflicts", "检查并处理已有 conflict.md"),
    ("task_05", "detect_contradictions", "检测文档间的事实矛盾"),
    ("task_06", "repair_links", "校验并修复所有文档链接"),
    ("task_07", "prune_conversations", "清理对话记录，仅保留最新两份"),
    ("task_08", "finalize_swap", "原子替换：备份原目录，工作副本取代"),
]


class KBOrganizerAgent:
    """知识库整理 Agent，采用 Plan-Execute (ReAct) 模式，LangGraph StateGraph 编排。

    依赖注入（全部必需）：
    - llm_service: LLMService
    - organization_service: KBOrganizationService
    """

    def __init__(self, llm_service: LLMService, organization_service: KBOrganizationService) -> None:
        self.llm_service = llm_service
        self.organization_service = organization_service
        self._log_file_path: str = ""
    
    def _setup_file_logging(self) -> None:
        """设置文件日志，记录每次运行详情到 test_log/ 目录"""
        log_dir = Path(__file__).parent.parent.parent / "test_log"
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = log_dir / f"kb_organizer_{timestamp}.log"
    
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
        file_handler.setFormatter(formatter)
    
        # Attach to root logger so all modules (services, storage) are captured
        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)
        root_logger.setLevel(logging.DEBUG)
    
        self._log_file_path = str(log_file)
        logger.info(f"日志文件已创建: {log_file}")
    
    async def run(self, target_path: str) -> KBOrganizerState:
        """执行完整的知识库整理流程，返回最终状态"""
        from src.agents.kb_organizer_graph import build_kb_organizer_graph
    
        self._setup_file_logging()
        logger.info(f"========== 知识库整理开始: {target_path} ==========")
    
        initial_state = self._initialize_state(target_path)
        graph = build_kb_organizer_graph(self)
        result = await graph.ainvoke(initial_state)
        return KBOrganizerState.model_validate(result)

    def _initialize_state(self, target_path: str) -> KBOrganizerState:
        """初始化状态：生成固定 8 步任务计划"""
        target = Path(target_path).resolve()
        tasks = [
            OrganizerTask(task_id=tid, task_type=ttype, description=desc)
            for tid, ttype, desc in _TASK_DEFINITIONS
        ]
        return KBOrganizerState(
            user_id=target.name,
            source_path=str(target),
            working_path=str(target.parent / f"{target.name}_temp"),
            task_plan=tasks,
            started_at=datetime.now(),
        )

    # ── LangGraph 节点 ─────────────────────────────────────────

    async def plan_node(self, state: KBOrganizerState) -> dict:
        """Plan 节点：获取下一个待执行任务，标记为 IN_PROGRESS"""
        current = state.get_current_task()
        if current:
            current.status = TaskStatus.IN_PROGRESS
            logger.info(f"═══ 开始执行任务: {current.task_type} (ID: {current.task_id}) ═══")
        return state.model_dump()

    async def execute_node(self, state: KBOrganizerState) -> dict:
        """Execute 节点：执行当前 IN_PROGRESS 任务"""
        tasks_ip = [t for t in state.task_plan if t.status == TaskStatus.IN_PROGRESS]
        if not tasks_ip:
            return state.model_dump()
        task = tasks_ip[0]
        try:
            with observe_step(
                f"execute.{task.task_type}",
                as_type="tool",
                input={"task_id": task.task_id, "task_type": task.task_type},
            ):
                await self._dispatch(task, state)
            if task.status == TaskStatus.IN_PROGRESS:
                task.status = TaskStatus.COMPLETED
            logger.info(f"✓ 任务完成: {task.task_type} - {task.result}")
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"✗ 任务失败: {task.task_type} - {e}", exc_info=True)
        return state.model_dump()

    async def observe_node(self, state: KBOrganizerState) -> dict:
        """Observe 节点：更新迭代计数，判断是否全部完成"""
        state.iteration_count += 1
        completed = sum(
            1 for t in state.task_plan
            if t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
        )
        total = len(state.task_plan)
        logger.info(f"[进度] 已完成 {completed}/{total} 个任务")
        if state.all_tasks_done():
            state.completed_at = datetime.now()
            logger.info(f"[进度] 全部完成，共 {state.iteration_count} 次迭代")
        return state.model_dump()

    def should_continue(self, state: KBOrganizerState) -> str:
        """条件边：判断是否继续循环"""
        if state.all_tasks_done():
            logger.info("[决策] 所有任务已完成，结束循环")
            return "end"
        logger.info("[决策] 还有未完成任务，继续循环")
        return "continue"

    # ── 任务路由与处理器 ────────────────────────────────────────

    async def _dispatch(self, task: OrganizerTask, state: KBOrganizerState) -> None:
        """根据 task_type 路由到对应处理器"""
        handler = getattr(self, f"_do_{task.task_type}", None)
        if handler is None:
            raise ValueError(f"未知任务类型: {task.task_type}")
        await handler(task, state)

    async def _do_setup_workspace(self, task: OrganizerTask, state: KBOrganizerState) -> None:
        """创建工作副本并扫描文件清单"""
        FileOperations.copy_directory(state.source_path, state.working_path)
        source_fm = self.organization_service.source_file_manager
        for category in ["events", "people", "timeline", "themes"]:
            items = source_fm.list_files(directory=category, recursive=True)
            md_files = [f for f in items if isinstance(f, str) and f.endswith(".md")]
            if md_files:
                state.all_files[category] = md_files
        total = sum(len(v) for v in state.all_files.values())
        task.result = f"工作副本已创建，共扫描到 {total} 个文档"

    async def _do_read_documents(self, task: OrganizerTask, state: KBOrganizerState) -> None:
        """阅读所有文档，建立内存索引"""
        source_fm = self.organization_service.source_file_manager
        count = 0
        for files in state.all_files.values():
            for fp in files:
                try:
                    state.document_contents[fp] = await source_fm.read_file(fp)
                    count += 1
                except Exception as e:
                    logger.warning(f"读取文件失败: {fp} - {e}")
        task.result = f"已读取 {count} 个文档到内存"

    async def _do_merge_duplicates(self, task: OrganizerTask, state: KBOrganizerState) -> None:
        """检测并合并重复文档"""
        svc = self.organization_service
        total_merged = 0
        for category in ["events", "people"]:
            files = state.all_files.get(category, [])
            if len(files) < 2:
                continue
            subdir_files: Dict[str, List[str]] = defaultdict(list)
            for f in files:
                parts = Path(f).parts
                subdir = str(Path(parts[0]) / parts[1]) if len(parts) >= 2 else category
                subdir_files[subdir].append(f)
            for sub_files in subdir_files.values():
                if len(sub_files) < 2:
                    continue
                groups = await svc.find_duplicate_groups(sub_files, category)
                for group in groups:
                    if len(group) >= 2:
                        record = await svc.merge_documents(group, category)
                        state.register_merge(
                            sources=record.source_files, target=record.target_file,
                            reason=record.merge_reason, details=record.preserved_details,
                        )
                        total_merged += len(group) - 1
        task.result = f"合并了 {total_merged} 个重复文档，产生 {len(state.merge_records)} 条合并记录"

    async def _do_check_conflicts(self, task: OrganizerTask, state: KBOrganizerState) -> None:
        """检查已有 conflict.md"""
        svc = self.organization_service
        if not svc.working_file_manager.file_exists("conflict.md"):
            task.status = TaskStatus.SKIPPED
            task.result = "未找到 conflict.md，跳过"
            return
        existing = await svc.load_conflict_file("conflict.md")
        retryable = [
            conflict for conflict in existing
            if not conflict.resolved and svc.conflict_has_new_evidence(conflict)
        ]
        retried_by_id = {
            conflict.conflict_id: conflict
            for conflict in await svc.resolve_conflicts(retryable, state.document_contents)
        }
        resolved_count = 0
        for conflict in existing:
            if not conflict.resolved:
                updated = retried_by_id.get(conflict.conflict_id, conflict)
                if updated.resolved:
                    resolved_count += 1
                state.conflict_items.append(updated)
            else:
                state.conflict_items.append(conflict)
        skipped_count = sum(
            1 for conflict in existing
            if not conflict.resolved and conflict.conflict_id not in retried_by_id
        )
        task.result = (
            f"处理 {len(existing)} 条已有矛盾，重试 {len(retryable)} 条，"
            f"解决 {resolved_count} 条，跳过 {skipped_count} 条无新证据的矛盾"
        )

    async def _do_detect_contradictions(self, task: OrganizerTask, state: KBOrganizerState) -> None:
        """检测文档间的事实矛盾"""
        svc = self.organization_service
        all_paths: List[str] = [f for files in state.all_files.values() for f in files]
        new_conflicts = await svc.detect_contradictions(all_paths)
        resolved_conflicts = await svc.resolve_conflicts(new_conflicts, state.document_contents)
        resolved_count = 0
        for idx, updated in enumerate(resolved_conflicts, 1):
            if updated.resolved:
                resolved_count += 1
            state.conflict_items.append(updated)
            # Log conflict details
            logger.info(
                f"[矛盾检测] 发现矛盾 #{idx}:\n"
                f"  类型: {updated.conflict_type}\n"
                f"  描述: {updated.description}\n"
                f"  涉及文件: {', '.join(updated.source_files)}\n"
                f"  证据: {updated.evidence or '无'}\n"
                f"  是否可解决: {updated.resolved}\n"
                f"  解决方案: {updated.resolution or '无'}"
            )
        active = state.get_active_conflicts()
        if active:
            await svc.save_conflict_file("conflict.md", active)
        task.result = f"检测到 {len(new_conflicts)} 条新矛盾，解决 {resolved_count} 条，{len(active)} 条待核实"

    async def _do_repair_links(self, task: OrganizerTask, state: KBOrganizerState) -> None:
        """修复所有文档链接"""
        svc = self.organization_service

        # Step 1: Apply merge-based redirects
        redirect_repaired = 0
        if state.link_redirect_map:
            redirect_repaired = await svc.repair_links(state.working_path, state.link_redirect_map)
            logger.info(f"[链接修复] 重定向修复了 {redirect_repaired} 个链接")

        # Step 2: Validate all links
        broken = await svc.validate_all_links(state.working_path)

        # Step 3: If broken links remain, use LLM to repair
        llm_repaired = 0
        if broken:
            logger.info(f"[链接修复] 仍有 {len(broken)} 个断链，调用 LLM 智能修复...")
            llm_repaired = await svc.repair_broken_links_with_llm(broken, state.working_path)

        # Step 4: Re-validate ALL links
        remaining = await svc.validate_all_links(state.working_path)
        total_repaired = redirect_repaired + llm_repaired

        if remaining:
            # Still broken links — mark as FAILED to trigger retry
            task.status = TaskStatus.FAILED
            task.error = f"修复 {total_repaired} 个链接后仍有 {len(remaining)} 个断链"
            logger.warning(f"[链接修复] 仍有 {len(remaining)} 个断链: {remaining[:5]}")
        else:
            task.result = f"全部链接已修复，共修复 {total_repaired} 个"

    async def _do_prune_conversations(self, task: OrganizerTask, state: KBOrganizerState) -> None:
        """清理对话记录，仅保留最新两份"""
        deleted = await self.organization_service.prune_conversations(state.working_path, keep_latest=2)
        task.result = f"删除 {len(deleted)} 个旧对话文件"
        task.affected_files = deleted

    async def _do_finalize_swap(self, task: OrganizerTask, state: KBOrganizerState) -> None:
        """原子替换：备份原目录，工作副本取代"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{state.source_path}_{timestamp}"
        FileOperations.rename_directory(state.source_path, backup_path)
        FileOperations.rename_directory(state.working_path, state.source_path)
        state.completed_at = datetime.now()
        task.result = f"原目录已备份为 {backup_path}，整理完成"
