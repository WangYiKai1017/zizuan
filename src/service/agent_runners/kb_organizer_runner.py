"""KB Organizer agent runner — wraps KBOrganizerAgent for SSE streaming."""
import shutil
from pathlib import Path

from src.service.agent_runners.base_runner import BaseAgentRunner
from src.service.sse_response import SSEEmitter
from src.agents.kb_organizer_agent import KBOrganizerAgent
from src.config.llm_config import LLMConfig
from src.services.llm_service import LLMService
from src.services.kb_organization_service import KBOrganizationService
from src.storage.file_operations import FileOperations
from src.storage.markdown_file_manager import MarkdownFileManager


class KBOrganizerRunner(BaseAgentRunner):
    """Runs KB organizer agent with SSE progress events."""

    def _get_kb_path(self) -> str:
        """Get the knowledge base path for this user."""
        project_root = Path(__file__).parent.parent.parent.parent
        return str(project_root / "knowledge_base" / self.user_id)

    def _create_agent(self, target_path: str) -> KBOrganizerAgent:
        """Create a fully-wired KBOrganizerAgent."""
        target = Path(target_path)
        parent = str(target.parent)
        folder_name = target.name

        config = LLMConfig.from_env()
        llm_service = LLMService(config)

        source_fm = MarkdownFileManager(base_path=parent, conversation_id=folder_name)
        working_fm = MarkdownFileManager(base_path=parent, conversation_id=f"{folder_name}_temp")
        file_ops = FileOperations()

        # Clean up any pre-existing temp directory
        working_path = Path(parent) / f"{folder_name}_temp"
        if working_path.exists():
            shutil.rmtree(working_path)

        service = KBOrganizationService(
            llm_service=llm_service,
            source_file_manager=source_fm,
            working_file_manager=working_fm,
            file_ops=file_ops,
        )

        return KBOrganizerAgent(
            llm_service=llm_service,
            organization_service=service,
        )

    async def run(self) -> None:
        """Execute KB organizer with SSE events."""
        target_path = self._get_kb_path()

        try:
            agent = self._create_agent(target_path)

            # Emit task_started
            await self.emitter.emit("task_started", {
                "user_id": self.user_id,
                "task_count": 7,
            })

            # Run the agent (monolithic call)
            result = await agent.run(target_path)

            # Emit progress for each task in the plan (post-hoc)
            if hasattr(result, 'task_plan') and result.task_plan:
                for task in result.task_plan:
                    await self.emitter.emit("task_progress", {
                        "task_id": task.task_id,
                        "task_type": task.task_type if hasattr(task, 'task_type') else "unknown",
                        "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                        "description": task.result or task.description or "",
                    })

            # Emit completed
            summary = {}
            if hasattr(result, 'merge_records'):
                summary["merge_records"] = [
                    r.model_dump() if hasattr(r, 'model_dump') else str(r)
                    for r in result.merge_records
                ]
            if hasattr(result, 'conflict_items'):
                summary["conflict_items"] = [
                    c.model_dump() if hasattr(c, 'model_dump') else str(c)
                    for c in result.conflict_items
                ]
            if hasattr(result, 'link_redirect_map'):
                summary["link_redirect_map"] = result.link_redirect_map

            await self.emitter.emit("task_completed", {
                "status": "completed",
                "iteration_count": getattr(result, 'iteration_count', 1),
                "summary": summary,
            })
            await self.emitter.emit_done("知识库整理完成")

        except Exception as e:
            await self.emitter.emit("failed", {
                "status": "failed",
                "error_code": "AGENT_ERROR",
                "message": str(e),
            })
            await self.emitter.emit_done("任务失败")
