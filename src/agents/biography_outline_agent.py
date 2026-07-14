"""大纲规划 Agent

负责分析知识库材料，生成/更新传记章节大纲。
支持增量更新：检测新材料后仅处理变化部分。
"""

import json
import logging
import re
from datetime import datetime

from src.models.biography_models import (
    AgentStatus,
    BiographyState,
    ChapterEntry,
    ChapterStatus,
    OutlineChange,
    OutlineDocument,
)
from src.models.biography_outline_state import OutlineAgentState
from src.services.biography_file_manager import BiographyFileManager
from src.services.biography_chapter_matcher import (
    chapter_identity_reason,
    deduplicate_chapters,
)
from src.services.biography_material_analyzer import BiographyMaterialAnalyzer
from src.services.llm_service import LLMService
from src.services.observability import observe_step

logger = logging.getLogger(__name__)


class BiographyOutlineAgent:
    """大纲规划 Agent"""

    def __init__(
        self,
        llm_service: LLMService,
        file_manager: BiographyFileManager,
        material_analyzer: BiographyMaterialAnalyzer,
    ):
        self.llm_service = llm_service
        self.file_manager = file_manager
        self.material_analyzer = material_analyzer

    async def run(self, user_id: str, kb_path: str) -> OutlineAgentState:
        """运行大纲规划 Agent

        Args:
            user_id: 用户标识
            kb_path: 知识库路径

        Returns:
            最终状态
        """
        from src.agents.biography_outline_graph import build_biography_outline_graph

        initial_state = OutlineAgentState(
            user_id=user_id,
            kb_path=kb_path,
            biography_path=self.file_manager.biography_path,
        )

        graph = build_biography_outline_graph(self)
        final_state = await graph.ainvoke(initial_state)

        # LangGraph returns dict, convert back
        if isinstance(final_state, dict):
            return OutlineAgentState.model_validate(final_state)
        return final_state

    # --- Graph Nodes ---

    async def scan_kb_node(self, state: OutlineAgentState) -> dict:
        """扫描知识库，检测变更

        1. 使用 material_analyzer 扫描和解析所有材料
        2. 检测是否有新增/变更文件（对比 .state.json）
        3. 加载已有的 outline.yaml（如果存在）
        """
        logger.info("=== [scan_kb] 开始扫描知识库 ===")

        # Load previous state for change detection
        prev_state = self.file_manager.load_state()
        current_hash = self.file_manager.compute_kb_hash()

        # Check if there are changes
        has_changes = current_hash != prev_state.kb_content_hash

        # Load and validate the existing outline even when KB content is unchanged.
        current_outline = self.file_manager.load_outline()
        needs_outline_repair = False
        if current_outline and current_outline.chapters:
            _, existing_duplicates = deduplicate_chapters(current_outline.chapters)
            needs_outline_repair = bool(existing_duplicates)

        if not has_changes and not needs_outline_repair:
            logger.info("[scan_kb] 知识库无变化，跳过处理")
            return {
                "has_changes": False,
                "needs_outline_repair": False,
                "status": AgentStatus.COMPLETED,
            }

        if not has_changes and needs_outline_repair:
            logger.warning("[scan_kb] 知识库无变化，但已有大纲包含重复章节")
            return {
                "has_changes": False,
                "needs_outline_repair": True,
                "changed_files": [],
                "current_outline": current_outline,
            }

        # Detect specific changed files
        changed_files = self.file_manager.detect_changes(prev_state)
        logger.info(f"[scan_kb] 检测到 {len(changed_files)} 个新增/变更文件")

        # Parse all materials
        with observe_step("scan_kb.scan_and_parse_materials", as_type="tool"):
            result = self.material_analyzer.scan_and_parse_all()

        return {
            "events": result["events"],
            "people": result["people"],
            "timeline": result["timeline"],
            "raw_materials_text": result["raw_content"],
            "has_changes": True,
            "needs_outline_repair": needs_outline_repair,
            "changed_files": changed_files,
            "current_outline": current_outline,
        }

    def should_continue_after_scan(self, state: OutlineAgentState) -> str:
        """判断扫描后是否继续处理"""
        if state.has_changes:
            return "continue"
        if state.needs_outline_repair:
            return "repair"
        if not state.has_changes:
            return "end"
        return "end"

    async def analyze_materials_node(self, state: OutlineAgentState) -> dict:
        """LLM 分析材料

        调用 biography_material_analyzer 模板，提取主题、叙事弧、人物关系、阶段分组
        """
        logger.info("=== [analyze_materials] 开始 LLM 材料分析 ===")

        # Determine existing themes (from current outline if available)
        existing_themes = ""
        if state.current_outline and state.current_outline.chapters:
            themes = list(set(ch.theme for ch in state.current_outline.chapters))
            existing_themes = "、".join(themes)

        # Call LLM
        result = await self.llm_service.invoke_with_template(
            template_name="biography_material_analyzer",
            variables={
                "materials_content": state.raw_materials_text,
                "existing_themes": existing_themes,
            },
            trace_node="analyze_materials",
        )

        if not result.success:
            logger.error(f"[analyze_materials] LLM 调用失败: {result.error}")
            return {
                "status": AgentStatus.FAILED,
                "error_message": f"材料分析失败: {result.error}",
            }

        logger.info("[analyze_materials] LLM 分析完成")
        logger.debug(f"[analyze_materials] 分析结果: {result.content[:200]}...")

        return {"analysis_result": result.content}

    async def generate_outline_node(self, state: OutlineAgentState) -> dict:
        """LLM 生成章节大纲

        调用 biography_outline_planner 模板，生成章节结构
        """
        logger.info("=== [generate_outline] 开始 LLM 大纲生成 ===")

        # Prepare existing outline text
        existing_outline_text = ""
        if state.current_outline:
            import yaml

            existing_outline_text = yaml.dump(
                state.current_outline.model_dump(),
                allow_unicode=True,
                default_flow_style=False,
            )

        # Prepare available materials list
        all_files = self.file_manager.scan_kb_files()
        available_materials = "\n".join(f"- {f}" for f in all_files)

        # Call LLM
        result = await self.llm_service.invoke_with_template(
            template_name="biography_outline_planner",
            variables={
                "analysis_result": state.analysis_result,
                "existing_outline": existing_outline_text,
                "available_materials": available_materials,
            },
            trace_node="generate_outline",
        )

        if not result.success:
            logger.error(f"[generate_outline] LLM 调用失败: {result.error}")
            return {
                "status": AgentStatus.FAILED,
                "error_message": f"大纲生成失败: {result.error}",
            }

        # Parse LLM output as JSON array of chapters
        try:
            content = result.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            chapters_data = json.loads(content)
            proposed_chapters = [
                ChapterEntry.model_validate(ch) for ch in chapters_data
            ]
            for chapter in proposed_chapters:
                chapter.source_materials = self._filter_existing_materials(chapter.source_materials)
                chapter.summary = self._build_grounded_chapter_summary(chapter)

            logger.info(
                f"[generate_outline] 生成了 {len(proposed_chapters)} 个章节"
            )
            for ch in proposed_chapters:
                logger.info(
                    f"  - {ch.id}: {ch.title} ({ch.life_stage}/{ch.theme})"
                )

            return {"proposed_chapters": proposed_chapters}

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"[generate_outline] 解析 LLM 输出失败: {e}")
            logger.error(
                f"[generate_outline] 原始输出: {result.content[:500]}"
            )
            return {
                "status": AgentStatus.FAILED,
                "error_message": f"大纲解析失败: {e}",
            }

    def _filter_existing_materials(self, source_materials: list[str]) -> list[str]:
        """只保留真实存在的 KB 素材，避免大纲引用不存在或无关文件。"""
        filtered = []
        for path in source_materials or []:
            if not path or path.startswith("biography/"):
                continue
            try:
                self.file_manager.read_kb_file(path)
            except Exception:
                continue
            if path not in filtered:
                filtered.append(path)
        return filtered

    def _build_grounded_chapter_summary(self, chapter: ChapterEntry) -> str:
        """用 source_materials 中的明确信息重写章节摘要，避免文学化补写。"""
        event_parts = []
        people_parts = []
        for path in chapter.source_materials:
            try:
                content = self.file_manager.read_kb_file(path)
            except Exception:
                continue
            if path.startswith("events/"):
                event_parts.append(self._summarize_event_material(content))
            elif path.startswith("people/"):
                people = self._extract_people_material(content)
                if people:
                    people_parts.append(people)

        event_parts = [part for part in event_parts if part]
        people_parts = [part for part in people_parts if part]

        if event_parts:
            summary = "；".join(event_parts[:2])
            if people_parts and chapter.theme == "家庭与亲情":
                summary = f"{summary}；本章还会交代{self._join_unique(people_parts)}。"
            return self._sanitize_outline_summary(summary)

        if people_parts:
            return self._sanitize_outline_summary(f"本章围绕{self._join_unique(people_parts)}展开，只写知识库中已确认的家庭关系与生活近况。")

        return self._sanitize_outline_summary(chapter.summary)

    def _summarize_event_material(self, content: str) -> str:
        title = self._extract_title(content)
        time_text = self._extract_field(content, "时间")
        description = self._extract_section(content, "事件描述").strip()
        details = self._extract_bullets(self._extract_section(content, "关键细节"))
        concrete_details = [
            detail for detail in details
            if not detail.startswith("我叫")
            and "故事留给" not in detail
            and "我和妻子" not in detail
            and "外孙女叫" not in detail
        ]
        detail_text = "，".join(concrete_details[:5])
        head = f"{time_text}，{title}" if time_text else title
        if detail_text:
            return f"{head}，关键细节包括{detail_text}"
        if description:
            return f"{head}：{description}"
        return head

    def _extract_people_material(self, content: str) -> str:
        name = self._extract_field(content, "姓名") or self._extract_title(content)
        role = self._extract_field(content, "关系")
        if name and role:
            return f"{name}（{role}）"
        return name

    def _extract_title(self, content: str) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return ""

    def _extract_field(self, content: str, field_name: str) -> str:
        match = re.search(rf"- \*\*{re.escape(field_name)}\*\*[：:](.+)", content)
        return match.group(1).strip() if match else ""

    def _extract_section(self, content: str, heading: str) -> str:
        pattern = rf"## {re.escape(heading)}\n(.*?)(?=\n## |\Z)"
        match = re.search(pattern, content, flags=re.S)
        return match.group(1).strip() if match else ""

    def _extract_bullets(self, section: str) -> list[str]:
        bullets = []
        for line in section.splitlines():
            line = line.strip()
            if line.startswith("- "):
                bullets.append(line[2:].strip())
        return bullets

    def _join_unique(self, items: list[str]) -> str:
        result = []
        for item in items:
            if item and item not in result:
                result.append(item)
        return "、".join(result)

    def _sanitize_outline_summary(self, summary: str) -> str:
        forbidden_replacements = {
            "稻浪": "安徽全椒农村",
            "父母弯下的背影": "早年家庭细节",
            "梦想的种子": "早年经历",
            "普通工人对国家最深情的告白": "一次职业经历",
            "荣耀": "经历",
            "技术骨干": "钳工",
            "推测": "",
            "推断": "",
            "推算": "",
        }
        text = summary or ""
        for old, new in forbidden_replacements.items():
            text = text.replace(old, new)
        return text.strip()

    @staticmethod
    def _planning_signature(chapter: ChapterEntry) -> tuple:
        return (
            chapter.title,
            chapter.life_stage,
            chapter.theme,
            tuple(chapter.source_materials),
            chapter.summary,
        )

    @staticmethod
    def _apply_proposed_plan(target: ChapterEntry, proposed: ChapterEntry) -> None:
        """Update editable planning fields while preserving chapter identity/state."""
        target.title = proposed.title
        target.life_stage = proposed.life_stage
        target.theme = proposed.theme
        target.source_materials = list(proposed.source_materials)
        target.summary = proposed.summary

    @staticmethod
    def _allocate_chapter_id(used_ids: set[str]) -> str:
        number = 1
        while f"ch{number:02d}" in used_ids:
            number += 1
        return f"ch{number:02d}"

    async def diff_and_update_node(self, state: OutlineAgentState) -> dict:
        """对比已有大纲，更新并写入文件

        - 新章节标记为 DRAFT
        - 已有 confirmed/written 章节保持不变（除非源材料变更则标记 OUTDATED）
        - 写入 outline.yaml 和 .state.json
        """
        logger.info("=== [diff_and_update] 开始对比和更新大纲 ===")

        changes_made = []

        if state.current_outline:
            # Incremental update mode
            final_outline = state.current_outline.model_copy(deep=True)
            deduplicated, removed_duplicates = deduplicate_chapters(
                final_outline.chapters
            )
            final_outline.chapters = deduplicated
            for removed, kept, reason in removed_duplicates:
                changes_made.append(
                    OutlineChange(
                        action="remove_duplicate",
                        chapter_id=removed.id,
                        reason=(
                            f"与章节 {kept.id} 重复（{reason}），保留状态更成熟的章节"
                        ),
                    )
                )
                logger.warning(
                    "[diff_and_update] 清理重复章节: %s -> %s (%s)",
                    removed.id,
                    kept.id,
                    reason,
                )

            used_ids = {ch.id for ch in final_outline.chapters}
            matched_ids: set[str] = set()

            # Match proposed chapters back to stable existing identities.
            for proposed in state.proposed_chapters:
                matched = None
                match_reason = None
                for existing in final_outline.chapters:
                    reason = chapter_identity_reason(existing, proposed)
                    if reason:
                        matched = existing
                        match_reason = reason
                        break

                if matched is not None:
                    if matched.id in matched_ids:
                        logger.warning(
                            "[diff_and_update] 忽略重复 proposed 章节: %s - %s，已匹配 %s",
                            proposed.id,
                            proposed.title,
                            matched.id,
                        )
                        continue
                    matched_ids.add(matched.id)

                    before = self._planning_signature(matched)
                    status_before = matched.status
                    changed_sources = set(state.changed_files)
                    has_relevant_material_change = bool(
                        changed_sources
                        & (set(matched.source_materials) | set(proposed.source_materials))
                    )

                    if matched.status in {ChapterStatus.DRAFT, ChapterStatus.OUTDATED}:
                        self._apply_proposed_plan(matched, proposed)
                    elif matched.status == ChapterStatus.WRITTEN and has_relevant_material_change:
                        self._apply_proposed_plan(matched, proposed)
                        matched.status = ChapterStatus.OUTDATED

                    after = self._planning_signature(matched)
                    if before != after or status_before != matched.status:
                        action = (
                            "mark_outdated"
                            if (
                                status_before == ChapterStatus.WRITTEN
                                and matched.status == ChapterStatus.OUTDATED
                            )
                            else "update"
                        )
                        changes_made.append(
                            OutlineChange(
                                action=action,
                                chapter_id=matched.id,
                                chapter_entry=matched,
                                reason=f"匹配已有章节（{match_reason}）并更新规划",
                            )
                        )
                    logger.info(
                        "[diff_and_update] 匹配已有章节: %s -> %s (%s)",
                        proposed.id,
                        matched.id,
                        match_reason,
                    )
                    continue

                if proposed.id in used_ids or not re.fullmatch(r"ch\d+", proposed.id):
                    proposed.id = self._allocate_chapter_id(used_ids)
                proposed.status = ChapterStatus.DRAFT
                final_outline.chapters.append(proposed)
                used_ids.add(proposed.id)
                changes_made.append(
                    OutlineChange(
                        action="add",
                        chapter_id=proposed.id,
                        chapter_entry=proposed,
                        reason="新材料产生的新章节",
                    )
                )
                logger.info(
                    f"[diff_and_update] 新增章节: {proposed.id} - {proposed.title}"
                )

            # Check if existing written chapters need outdating
            for existing_ch in final_outline.chapters:
                if existing_ch.status == ChapterStatus.WRITTEN:
                    # Check if any source materials were in changed_files
                    if any(
                        f in state.changed_files
                        for f in existing_ch.source_materials
                    ):
                        existing_ch.status = ChapterStatus.OUTDATED
                        changes_made.append(
                            OutlineChange(
                                action="mark_outdated",
                                chapter_id=existing_ch.id,
                                reason="源材料已更新",
                            )
                        )
                        logger.info(
                            f"[diff_and_update] 标记过时: {existing_ch.id}"
                        )

            # Update version
            final_outline.version += 1
            final_outline.last_updated = datetime.now()

        else:
            # First run - create new outline
            unique_proposed, removed_duplicates = deduplicate_chapters(
                state.proposed_chapters,
                match_by_id=False,
            )
            used_ids: set[str] = set()
            for chapter in unique_proposed:
                if chapter.id in used_ids or not re.fullmatch(r"ch\d+", chapter.id):
                    chapter.id = self._allocate_chapter_id(used_ids)
                used_ids.add(chapter.id)

            final_outline = OutlineDocument(
                title="我的人生故事",
                author=state.user_id,
                version=1,
                last_updated=datetime.now(),
                chapters=unique_proposed,
            )
            for removed, kept, reason in removed_duplicates:
                logger.warning(
                    "[diff_and_update] 首次生成忽略重复章节: %s -> %s (%s)",
                    removed.id,
                    kept.id,
                    reason,
                )
            # All chapters start as DRAFT
            for ch in final_outline.chapters:
                ch.status = ChapterStatus.DRAFT
                changes_made.append(
                    OutlineChange(
                        action="add",
                        chapter_id=ch.id,
                        chapter_entry=ch,
                        reason="首次生成大纲",
                    )
                )

        # Save outline.yaml
        with observe_step(
            "diff_and_update.save_outline",
            as_type="tool",
            metadata={"chapter_count": len(final_outline.chapters)},
        ):
            self.file_manager.save_outline(final_outline)
            new_state = BiographyState(
                last_outline_run=datetime.now(),
                kb_content_hash=self.file_manager.compute_kb_hash(),
                processed_files=self.file_manager.scan_kb_files(),
                chapter_versions={
                    ch.id: final_outline.version for ch in final_outline.chapters
                },
            )
            self.file_manager.save_state(new_state)
        logger.info(
            f"[diff_and_update] 已保存大纲，共 {len(final_outline.chapters)} 章"
        )

        return {
            "final_outline": final_outline,
            "changes_made": changes_made,
            "status": AgentStatus.COMPLETED,
        }
