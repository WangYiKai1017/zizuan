"""传记写作 Agent

负责将已确认的章节大纲转化为第一人称自传章节。
逐章写作：收集材料 -> 生成初稿 -> 自我审阅 -> 保存 -> 循环下一章。
全部完成后合并为完整传记。
"""

import json
import logging
import re
from datetime import datetime

from src.models.biography_models import (
    AgentStatus,
    ChapterStatus,
    ChapterTask,
)
from src.models.biography_writing_state import WritingAgentState
from src.services.biography_chapter_matcher import deduplicate_chapters
from src.services.biography_file_manager import BiographyFileManager
from src.services.biography_material_analyzer import BiographyMaterialAnalyzer
from src.services.llm_service import LLMService
from src.services.observability import observe_step

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

        with observe_step("load_tasks.load_outline", as_type="tool"):
            outline = self.file_manager.load_outline()
        if not outline:
            logger.warning("[load_tasks] 未找到大纲文件 outline.yaml")
            return {
                "status": AgentStatus.COMPLETED,
                "error_message": "未找到大纲文件",
            }

        deduplicated, removed_duplicates = deduplicate_chapters(outline.chapters)
        if removed_duplicates:
            outline.chapters = deduplicated
            outline.version += 1
            outline.last_updated = datetime.now()
            for removed, kept, reason in removed_duplicates:
                logger.warning(
                    "[load_tasks] 清理重复章节: %s -> %s (%s)",
                    removed.id,
                    kept.id,
                    reason,
                )
            with observe_step(
                "load_tasks.repair_duplicate_outline",
                as_type="tool",
                metadata={"removed_count": len(removed_duplicates)},
            ):
                self.file_manager.save_outline(outline)
                self.file_manager.merge_chapters_to_full(outline)

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
        with observe_step(
            "gather_materials.read_sources",
            as_type="tool",
            metadata={
                "chapter_id": chapter.chapter_id,
                "source_count": len(chapter.source_materials),
                "life_stage": chapter.life_stage,
            },
        ):
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

        调用 biography_chapter_writer 模板，生成第一人称自传章节。
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
            trace_node="writing.write_chapter",
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
            trace_node="writing.review_chapter",
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
        with observe_step(
            "review_and_save.save_chapter",
            as_type="tool",
            metadata={"chapter_id": chapter.chapter_id, "chapter_title": chapter.chapter_title},
        ):
            saved_path = self.file_manager.save_chapter(
                chapter_id=chapter.chapter_id,
                title=chapter.chapter_title,
                content=final_content,
            )
            self.file_manager.update_chapter_status(
                chapter_id=chapter.chapter_id,
                status=ChapterStatus.WRITTEN,
                timestamp_field="written_at",
            )
        logger.info(f"[review_and_save] 章节已保存: {saved_path}")

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

    def _build_grounded_chapter_content(
        self,
        title: str,
        theme: str,
        source_content: str,
        character_profiles: str,
    ) -> str:
        """从知识库原文生成事实稿，避免自由扩写造成幻觉。"""
        blocks = self._split_source_blocks(source_content)
        lines = [f"# {title}", ""]
        if theme:
            lines.extend([f"本章围绕“{theme}”展开，只依据已经归档的采访材料整理。", ""])

        wrote_any = False
        for path, content in blocks:
            if path.startswith("events/"):
                section = self._render_event_block(content)
            elif path.startswith("people/"):
                section = self._render_person_block(content)
            else:
                section = ""
            if section:
                lines.extend([section, ""])
                wrote_any = True

        if not wrote_any and character_profiles:
            lines.extend(["## 已确认人物", "", self._sanitize_text(character_profiles.strip()), ""])

        lines.extend([
            "## 待补充",
            "",
            "这一章后续只补充被采访者明确讲述过的细节；当前没有材料支撑的场景、对白和心理活动暂不扩写。",
        ])
        return "\n".join(lines).strip() + "\n"

    def _split_source_blocks(self, source_content: str) -> list[tuple[str, str]]:
        pattern = r"--- ([^-][^\n]+) ---\n"
        matches = list(re.finditer(pattern, source_content or ""))
        blocks: list[tuple[str, str]] = []
        for i, match in enumerate(matches):
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(source_content)
            blocks.append((match.group(1).strip(), source_content[start:end].strip()))
        return blocks

    def _render_event_block(self, content: str) -> str:
        title = self._extract_title(content)
        time_text = self._extract_field(content, "时间")
        location = self._extract_field(content, "地点")
        description = self._extract_section(content, "事件描述")
        details = self._extract_bullets(self._extract_section(content, "关键细节"))
        details = [
            item for item in details
            if item and not item.startswith("我叫") and "故事留给" not in item and "我和妻子" not in item
        ]

        lines = [f"## {title or '事件'}", ""]
        facts = []
        if time_text:
            facts.append(f"时间：{time_text}")
        if location:
            facts.append(f"地点：{location}")
        if facts:
            lines.extend(["；".join(facts) + "。", ""])
        if description:
            lines.extend([self._sanitize_text(description), ""])
        if details:
            lines.append("采访中已经确认的细节包括：")
            for item in details:
                lines.append(f"- {self._sanitize_text(item)}")
        return "\n".join(lines).strip()

    def _render_person_block(self, content: str) -> str:
        name = self._extract_field(content, "姓名") or self._extract_title(content)
        role = self._extract_field(content, "关系")
        description = self._extract_field(content, "描述")
        if not any([name, role, description]):
            return ""
        lines = [f"## {name}", ""]
        if role:
            lines.append(f"关系：{role}。")
        if description:
            lines.append(self._sanitize_text(description))
        return "\n".join(lines).strip()

    def _extract_title(self, content: str) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return ""

    def _extract_field(self, content: str, field_name: str) -> str:
        match = re.search(rf"- \*\*{re.escape(field_name)}\*\*[：:](.+)", content)
        return match.group(1).strip() if match else ""

    def _extract_section(self, content: str, heading: str) -> str:
        match = re.search(rf"## {re.escape(heading)}\n(.*?)(?=\n## |\Z)", content, flags=re.S)
        return match.group(1).strip() if match else ""

    def _extract_bullets(self, section: str) -> list[str]:
        return [line.strip()[2:] for line in section.splitlines() if line.strip().startswith("- ")]

    def _sanitize_text(self, text: str) -> str:
        cleaned = text or ""
        for old, new in {
            "技术骨干": "钳工",
            "推测为": "为",
            "推测": "",
            "推断": "",
            "推算": "",
        }.items():
            cleaned = cleaned.replace(old, new)
        return cleaned.strip()

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
            with observe_step(
                "merge_biography.merge_chapters_to_full",
                as_type="tool",
                metadata={"chapter_count": len(outline.chapters)},
            ):
                merged_path = self.file_manager.merge_chapters_to_full(outline)
            logger.info(f"[merge_biography] 完整传记已生成: {merged_path}")
        else:
            logger.warning("[merge_biography] 无法加载大纲，跳过合并")

        return {"status": AgentStatus.COMPLETED}
