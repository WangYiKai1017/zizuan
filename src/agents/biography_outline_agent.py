"""大纲规划 Agent

负责分析知识库材料，生成/更新传记章节大纲。
支持增量更新：检测新材料后仅处理变化部分。
"""

import json
import logging
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
from src.services.biography_material_analyzer import BiographyMaterialAnalyzer
from src.services.llm_service import LLMService

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

        if not has_changes:
            logger.info("[scan_kb] 知识库无变化，跳过处理")
            return {
                "has_changes": False,
                "status": AgentStatus.COMPLETED,
            }

        # Detect specific changed files
        changed_files = self.file_manager.detect_changes(prev_state)
        logger.info(f"[scan_kb] 检测到 {len(changed_files)} 个新增/变更文件")

        # Parse all materials
        result = self.material_analyzer.scan_and_parse_all()

        # Load existing outline if any
        current_outline = self.file_manager.load_outline()

        return {
            "events": result["events"],
            "people": result["people"],
            "timeline": result["timeline"],
            "raw_materials_text": result["raw_content"],
            "has_changes": True,
            "changed_files": changed_files,
            "current_outline": current_outline,
        }

    def should_continue_after_scan(self, state: OutlineAgentState) -> str:
        """判断扫描后是否继续处理"""
        if not state.has_changes:
            return "end"
        return "continue"

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
            existing_ids = {ch.id for ch in final_outline.chapters}

            # Add new chapters
            for proposed in state.proposed_chapters:
                if proposed.id not in existing_ids:
                    proposed.status = ChapterStatus.DRAFT
                    final_outline.chapters.append(proposed)
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
            final_outline = OutlineDocument(
                title="我的人生故事",
                author=state.user_id,
                version=1,
                last_updated=datetime.now(),
                chapters=state.proposed_chapters,
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
        self.file_manager.save_outline(final_outline)
        logger.info(
            f"[diff_and_update] 已保存大纲，共 {len(final_outline.chapters)} 章"
        )

        # Update .state.json
        new_state = BiographyState(
            last_outline_run=datetime.now(),
            kb_content_hash=self.file_manager.compute_kb_hash(),
            processed_files=self.file_manager.scan_kb_files(),
            chapter_versions={
                ch.id: final_outline.version for ch in final_outline.chapters
            },
        )
        self.file_manager.save_state(new_state)

        return {
            "final_outline": final_outline,
            "changes_made": changes_made,
            "status": AgentStatus.COMPLETED,
        }
