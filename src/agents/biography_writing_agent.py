"""传记写作 Agent

负责将已确认的章节大纲转化为第一人称口述体传记散文。
逐章写作：收集材料 -> 生成初稿 -> 自我审阅 -> 保存 -> 循环下一章。
全部完成后合并为完整传记。
"""

import json
import logging
from datetime import datetime

from src.models.biography_models import (
    AgentStatus,
    ChapterStatus,
    ChapterTask,
)
from src.models.biography_writing_state import WritingAgentState
from src.services.biography_file_manager import BiographyFileManager
from src.services.biography_material_analyzer import BiographyMaterialAnalyzer
from src.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class BiographyWritingAgent:
    """传记写作 Agent"""

    def __init__(
        self,
        llm_service: LLMService,
        file_manager: BiographyFileManager,
        material_analyzer: BiographyMaterialAnalyzer,
    ):
        self.llm_service = llm_service
        self.file_manager = file_manager
        self.material_analyzer = material_analyzer

    async def run(self, user_id: str, kb_path: str) -> WritingAgentState:
        """运行传记写作 Agent"""
        from src.agents.biography_writing_graph import build_biography_writing_graph

        initial_state = WritingAgentState(
            user_id=user_id,
            kb_path=kb_path,
            biography_path=self.file_manager.biography_path,
        )

        graph = build_biography_writing_graph(self)
        final_state = await graph.ainvoke(initial_state)

        if isinstance(final_state, dict):
            return WritingAgentState.model_validate(final_state)
        return final_state

    # --- Graph Nodes ---

    async def load_tasks_node(self, state: WritingAgentState) -> dict:
        """加载写作任务

        读取 outline.yaml，筛选 status == "confirmed" 的章节，构建任务队列。
        """
        logger.info("=== [load_tasks] 加载写作任务 ===")

        outline = self.file_manager.load_outline()
        if not outline:
            logger.warning("[load_tasks] 未找到大纲文件 outline.yaml")
            return {
                "status": AgentStatus.COMPLETED,
                "error_message": "未找到大纲文件",
            }

        # Filter confirmed chapters
        confirmed = [
            ch for ch in outline.chapters
            if ch.status == ChapterStatus.CONFIRMED
        ]

        if not confirmed:
            logger.info("[load_tasks] 没有待写作的已确认章节")
            return {
                "chapters_to_write": [],
                "status": AgentStatus.COMPLETED,
            }

        # Build task queue
        tasks = [
            ChapterTask(
                chapter_id=ch.id,
                chapter_title=ch.title,
                life_stage=ch.life_stage,
                theme=ch.theme,
                source_materials=ch.source_materials,
                summary=ch.summary,
            )
            for ch in confirmed
        ]

        logger.info(f"[load_tasks] 找到 {len(tasks)} 个待写作章节:")
        for t in tasks:
            logger.info(f"  - {t.chapter_id}: {t.chapter_title}")

        return {
            "chapters_to_write": tasks,
            "current_chapter": tasks[0],
            "current_chapter_index": 0,
        }

    def should_continue_after_load(self, state: WritingAgentState) -> str:
        """加载后判断是否有任务"""
        if not state.chapters_to_write:
            return "end"
        return "continue"

    async def gather_materials_node(self, state: WritingAgentState) -> dict:
        """为当前章节收集写作材料

        读取章节的 source_materials + 相关人物 + 时间线上下文
        """
        chapter = state.current_chapter
        logger.info(
            f"=== [gather_materials] 收集材料: {chapter.chapter_id} - {chapter.chapter_title} ==="
        )

        # Use material_analyzer to gather all needed content
        materials = self.material_analyzer.gather_chapter_materials(
            source_materials=chapter.source_materials,
            life_stage=chapter.life_stage,
        )

        logger.info(f"[gather_materials] 源材料: {len(materials['source_content'])} 字符")
        logger.info(f"[gather_materials] 人物档案: {len(materials['character_profiles'])} 字符")
        logger.info(f"[gather_materials] 时间线: {len(materials['timeline_context'])} 字符")

        return {
            "source_content": materials["source_content"],
            "character_profiles": materials["character_profiles"],
            "timeline_context": materials["timeline_context"],
        }

    async def write_chapter_node(self, state: WritingAgentState) -> dict:
        """LLM 撰写章节

        调用 biography_chapter_writer 模板，生成第一人称口述体散文。
        """
        chapter = state.current_chapter
        logger.info(f"=== [write_chapter] 撰写章节: {chapter.chapter_title} ===")

        result = await self.llm_service.invoke_with_template(
            template_name="biography_chapter_writer",
            variables={
                "chapter_title": chapter.chapter_title,
                "chapter_theme": chapter.theme,
                "life_stage": chapter.life_stage,
                "source_materials": state.source_content,
                "character_profiles": state.character_profiles,
                "timeline_context": state.timeline_context,
            },
        )

        if not result.success:
            logger.error(f"[write_chapter] LLM 调用失败: {result.error}")
            return {
                "status": AgentStatus.FAILED,
                "error_message": f"章节写作失败: {result.error}",
            }

        draft = result.content.strip()
        logger.info(f"[write_chapter] 初稿生成完成，{len(draft)} 字符")

        return {"draft_content": draft}

    async def review_and_save_node(self, state: WritingAgentState) -> dict:
        """LLM 审阅并保存章节

        1. 调用 biography_chapter_reviewer 进行自我审阅
        2. 如果需要修订则使用修订版本，否则使用初稿
        3. 保存章节文件
        4. 更新 outline.yaml 中的状态
        5. 推进到下一章
        """
        chapter = state.current_chapter
        logger.info(f"=== [review_and_save] 审阅章节: {chapter.chapter_title} ===")

        # Call reviewer
        review_result = await self.llm_service.invoke_with_template(
            template_name="biography_chapter_reviewer",
            variables={
                "chapter_content": state.draft_content,
                "source_materials": state.source_content,
                "chapter_title": chapter.chapter_title,
            },
        )

        final_content = state.draft_content  # Default to draft

        if review_result.success:
            try:
                content = review_result.content.strip()
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                review_data = json.loads(content)
                score = review_data.get("score", 7)
                issues = review_data.get("issues", [])
                needs_revision = review_data.get("needs_revision", False)

                logger.info(f"[review_and_save] 审阅评分: {score}/10")
                if issues:
                    for issue in issues:
                        logger.info(
                            f"[review_and_save] 问题: [{issue.get('type')}] {issue.get('description')}"
                        )

                if needs_revision and review_data.get("revised_content"):
                    final_content = review_data["revised_content"]
                    logger.info("[review_and_save] 使用修订版本")
                else:
                    logger.info("[review_and_save] 初稿通过审阅，无需修订")

            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"[review_and_save] 审阅结果解析失败: {e}，使用初稿")
        else:
            logger.warning(
                f"[review_and_save] 审阅 LLM 调用失败: {review_result.error}，使用初稿"
            )

        # Save chapter file
        saved_path = self.file_manager.save_chapter(
            chapter_id=chapter.chapter_id,
            title=chapter.chapter_title,
            content=final_content,
        )
        logger.info(f"[review_and_save] 章节已保存: {saved_path}")

        # Update outline.yaml status
        self.file_manager.update_chapter_status(
            chapter_id=chapter.chapter_id,
            status=ChapterStatus.WRITTEN,
            timestamp_field="written_at",
        )

        # Advance to next chapter
        completed = state.completed_chapters + [chapter.chapter_id]
        next_index = state.current_chapter_index + 1
        next_chapter = None
        if next_index < len(state.chapters_to_write):
            next_chapter = state.chapters_to_write[next_index]

        return {
            "reviewed_content": final_content,
            "completed_chapters": completed,
            "current_chapter_index": next_index,
            "current_chapter": next_chapter,
        }

    def should_continue(self, state: WritingAgentState) -> str:
        """判断是否继续写下一章"""
        if state.current_chapter_index < len(state.chapters_to_write):
            logger.info(
                f"[should_continue] 还有 {len(state.chapters_to_write) - state.current_chapter_index} 章待写"
            )
            return "continue"
        logger.info("[should_continue] 所有章节写作完成，开始合并")
        return "merge"

    async def merge_biography_node(self, state: WritingAgentState) -> dict:
        """合并所有章节为完整传记"""
        logger.info("=== [merge_biography] 合并完整传记 ===")

        outline = self.file_manager.load_outline()
        if outline:
            merged_path = self.file_manager.merge_chapters_to_full(outline)
            logger.info(f"[merge_biography] 完整传记已生成: {merged_path}")
        else:
            logger.warning("[merge_biography] 无法加载大纲，跳过合并")

        return {"status": AgentStatus.COMPLETED}
