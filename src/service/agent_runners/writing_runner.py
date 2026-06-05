"""Biography Writing agent runner — wraps BiographyWritingAgent for SSE streaming."""
import os
from pathlib import Path

from src.service.agent_runners.base_runner import BaseAgentRunner
from src.service.sse_response import SSEEmitter
from src.agents.biography_writing_agent import BiographyWritingAgent
from src.config.llm_config import get_default_config
from src.services.llm_service import LLMService
from src.services.biography_file_manager import BiographyFileManager
from src.services.biography_material_analyzer import BiographyMaterialAnalyzer
from src.services.observability import observability_context, observe_step


class WritingRunner(BaseAgentRunner):
    """Runs biography writing agent with SSE progress events."""

    def _get_kb_path(self) -> str:
        """Get the knowledge base path for this user."""
        project_root = Path(__file__).parent.parent.parent.parent
        return str(project_root / "knowledge_base" / self.user_id)

    def _create_agent(self, kb_path: str):
        """Create a fully-wired BiographyWritingAgent."""
        config = get_default_config()
        llm_service = LLMService(config)
        file_manager = BiographyFileManager(kb_path)
        material_analyzer = BiographyMaterialAnalyzer(file_manager)

        return BiographyWritingAgent(
            llm_service=llm_service,
            file_manager=file_manager,
            material_analyzer=material_analyzer,
        )

    async def run(self) -> None:
        """Execute writing agent with SSE events."""
        kb_path = self._get_kb_path()

        try:
            with observability_context(self.build_trace_context(
                agent="biography_writing",
                operation="run",
            )):
                agent = self._create_agent(kb_path)

                # Load outline to count confirmed chapters
                file_manager = BiographyFileManager(kb_path)
                with observe_step("load_outline", as_type="tool", input={"kb_path": kb_path}):
                    outline = file_manager.load_outline()
                chapters_to_write = 0
                if outline:
                    from src.models.biography_models import ChapterStatus
                    chapters_to_write = sum(
                        1 for ch in outline.chapters if ch.status == ChapterStatus.CONFIRMED
                    )

                # Emit task_started
                await self.emitter.emit("task_started", {
                    "user_id": self.user_id,
                    "chapters_to_write": chapters_to_write,
                })

                if chapters_to_write == 0:
                    await self.emitter.emit("completed", {
                        "status": "completed",
                        "message": "没有待写作的章节（需要先确认大纲章节）",
                        "completed_chapters": [],
                    })
                    await self.emitter.emit_done("无待写作章节")
                    return

                # Emit loading_tasks
                confirmed_ids = []
                if outline:
                    from src.models.biography_models import ChapterStatus
                    confirmed_ids = [
                        ch.id for ch in outline.chapters if ch.status == ChapterStatus.CONFIRMED
                    ]

                await self.emitter.emit("loading_tasks", {
                    "step": "loading_tasks",
                    "message": "正在加载写作任务...",
                    "chapters": confirmed_ids,
                })

                # Run agent
                with observe_step("run_agent", as_type="agent", input={"kb_path": kb_path}):
                    result = await agent.run(user_id=self.user_id, kb_path=kb_path)

            # Emit per-chapter results (post-hoc since agent is monolithic)
            if hasattr(result, 'completed_chapters') and result.completed_chapters:
                total = len(result.completed_chapters)
                for idx, ch_id in enumerate(result.completed_chapters, 1):
                    await self.emitter.emit("saved", {
                        "step": "saved",
                        "chapter_id": ch_id,
                        "progress": f"{idx}/{total}",
                    })

            # Emit merging
            await self.emitter.emit("merging", {
                "step": "merging",
                "message": "正在合并为完整传记...",
            })

            # Emit completed
            full_bio_path = os.path.join(kb_path, "biography", "full_biography.md")
            total_word_count = 0
            if os.path.exists(full_bio_path):
                with open(full_bio_path, 'r', encoding='utf-8') as f:
                    total_word_count = len(f.read())

            await self.emitter.emit("completed", {
                "status": "completed",
                "completed_chapters": result.completed_chapters if hasattr(result, 'completed_chapters') else [],
                "total_word_count": total_word_count,
                "full_biography_path": "biography/full_biography.md",
            })
            await self.emitter.emit_done("传记写作完成")

        except Exception as e:
            await self.emitter.emit("failed", {
                "status": "failed",
                "error_code": "AGENT_ERROR",
                "message": str(e),
            })
            await self.emitter.emit_done("任务失败")
