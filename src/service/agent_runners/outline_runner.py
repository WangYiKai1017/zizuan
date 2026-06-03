"""Biography Outline agent runner — wraps BiographyOutlineAgent for SSE streaming."""
from pathlib import Path

from src.service.agent_runners.base_runner import BaseAgentRunner
from src.service.sse_response import SSEEmitter
from src.agents.biography_outline_agent import BiographyOutlineAgent
from src.config.llm_config import get_default_config
from src.services.llm_service import LLMService
from src.services.biography_file_manager import BiographyFileManager
from src.services.biography_material_analyzer import BiographyMaterialAnalyzer
from src.services.observability import ObservabilityContext, observability_context, observe_step


class OutlineRunner(BaseAgentRunner):
    """Runs biography outline agent with SSE progress events."""

    def _get_kb_path(self) -> str:
        """Get the knowledge base path for this user."""
        project_root = Path(__file__).parent.parent.parent.parent
        return str(project_root / "knowledge_base" / self.user_id)

    def _create_agent(self, kb_path: str):
        """Create a fully-wired BiographyOutlineAgent."""
        config = get_default_config()
        llm_service = LLMService(config)
        file_manager = BiographyFileManager(kb_path)
        material_analyzer = BiographyMaterialAnalyzer(file_manager)

        return BiographyOutlineAgent(
            llm_service=llm_service,
            file_manager=file_manager,
            material_analyzer=material_analyzer,
        )

    async def run(self) -> None:
        """Execute outline agent with SSE events."""
        kb_path = self._get_kb_path()

        try:
            with observability_context(ObservabilityContext(
                agent="biography_outline",
                operation="generate",
                user_id=self.user_id,
                session_id=self.session_id,
            )):
                agent = self._create_agent(kb_path)

                # Emit task_started
                await self.emitter.emit("task_started", {
                    "user_id": self.user_id,
                    "mode": "generate",
                })

                # Emit scanning
                await self.emitter.emit("scanning", {
                    "step": "scanning",
                    "message": "正在扫描知识库材料...",
                })

                # Run agent
                with observe_step("run_agent", as_type="agent", input={"kb_path": kb_path}):
                    result = await agent.run(user_id=self.user_id, kb_path=kb_path)

            # Check if no changes
            if hasattr(result, 'has_changes') and not result.has_changes:
                await self.emitter.emit("completed", {
                    "status": "completed",
                    "has_changes": False,
                    "message": "知识库无新增材料，大纲无需更新",
                })
                await self.emitter.emit_done("无需更新")
                return

            # Emit analyzing
            await self.emitter.emit("analyzing", {
                "step": "analyzing",
                "message": "分析完成",
            })

            # Emit generating
            if hasattr(result, 'final_outline') and result.final_outline:
                chapters_count = len(result.final_outline.chapters)
                await self.emitter.emit("generating", {
                    "step": "generating",
                    "message": f"生成了 {chapters_count} 个章节",
                    "chapters_count": chapters_count,
                })

            # Emit completed with outline data
            outline_data = None
            if hasattr(result, 'final_outline') and result.final_outline:
                outline_data = result.final_outline.model_dump(mode="json")

            changes_data = []
            if hasattr(result, 'changes_made') and result.changes_made:
                changes_data = [
                    c.model_dump(mode="json") if hasattr(c, 'model_dump')
                    else {"action": c.action, "chapter_id": c.chapter_id, "reason": c.reason}
                    for c in result.changes_made
                ]

            await self.emitter.emit("completed", {
                "status": "completed",
                "outline": outline_data,
                "changes_made": changes_data,
            })
            await self.emitter.emit_done("大纲生成完成")

        except Exception as e:
            await self.emitter.emit("failed", {
                "status": "failed",
                "error_code": "AGENT_ERROR",
                "message": str(e),
            })
            await self.emitter.emit_done("任务失败")
