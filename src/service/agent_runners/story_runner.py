"""Story generation runner — wraps StoryGenerationAgent for SSE streaming."""

from pathlib import Path

from src.agents.story_generation_agent import (
    REQUIRED_EVENT_COUNT,
    StoryGenerationAgent,
    StoryOutputInvalidError,
    StoryStateSaveError,
)
from src.config.llm_config import get_default_config
from src.service.agent_runners.base_runner import BaseAgentRunner
from src.services.llm_service import LLMService
from src.services.observability import ObservabilityContext, observability_context, observe_step


class StoryRunner(BaseAgentRunner):
    """Runs story generation with SSE progress events."""

    def _get_kb_path(self) -> str:
        project_root = Path(__file__).parent.parent.parent.parent
        return str(project_root / "knowledge_base" / self.user_id)

    def _create_agent(self, kb_path: str) -> StoryGenerationAgent:
        config = get_default_config()
        llm_service = LLMService(config)
        return StoryGenerationAgent(kb_path=kb_path, llm_service=llm_service)

    async def run(self) -> None:
        kb_path = self._get_kb_path()

        try:
            with observability_context(ObservabilityContext(
                agent="story_generation",
                operation="generate",
                user_id=self.user_id,
                session_id=self.session_id,
            )):
                agent = self._create_agent(kb_path)

                await self.emitter.emit("task_started", {
                    "user_id": self.user_id,
                    "required_event_count": REQUIRED_EVENT_COUNT,
                })

                with observe_step("story_generation.scan_events", as_type="tool"):
                    events = agent.load_unconsumed_events()

                available_count = len(events)
                await self.emitter.emit("scanning", {
                    "step": "scanning",
                    "message": f"扫描到 {available_count} 个未生成故事的事件",
                    "available_events": available_count,
                    "required_events": REQUIRED_EVENT_COUNT,
                })

                if available_count < REQUIRED_EVENT_COUNT:
                    await self.emitter.emit("failed", {
                        "status": "failed",
                        "error_code": "INSUFFICIENT_EVENTS",
                        "message": "未生成故事的事件不足15个",
                        "available_events": available_count,
                        "required_events": REQUIRED_EVENT_COUNT,
                    })
                    await self.emitter.emit_done("任务失败")
                    return

                selected_events = agent.select_events(events)
                await self.emitter.emit("generating", {
                    "step": "generating",
                    "message": "正在根据最早的 15 个事件生成故事...",
                    "selected_event_count": len(selected_events),
                    "selected_event_paths": [event.path for event in selected_events],
                })

                story = await agent.generate_story(selected_events)

                with observe_step("story_generation.save_story", as_type="tool"):
                    saved = agent.save_story_and_mark_consumed(story, selected_events)

                remaining_count = available_count - len(selected_events)
                await self.emitter.emit("saved", {
                    "step": "saved",
                    "message": "故事已保存，事件消费状态已更新",
                    "story_id": saved.story_id,
                    "story_path": saved.story_path,
                    "consumed_event_count": len(saved.event_paths),
                })
                await self.emitter.emit("completed", {
                    "status": "completed",
                    "story_id": saved.story_id,
                    "story_path": saved.story_path,
                    "consumed_event_count": len(saved.event_paths),
                    "remaining_event_count": remaining_count,
                })
                await self.emitter.emit_done("故事生成完成")

        except StoryStateSaveError as e:
            await self.emitter.emit("failed", {
                "status": "failed",
                "error_code": "STATE_SAVE_FAILED",
                "message": str(e),
                "story_path": e.story_path,
            })
            await self.emitter.emit_done("任务失败")
        except StoryOutputInvalidError as e:
            await self.emitter.emit("failed", {
                "status": "failed",
                "error_code": "STORY_GENERATION_FAILED",
                "message": str(e),
            })
            await self.emitter.emit_done("任务失败")
        except Exception as e:
            await self.emitter.emit("failed", {
                "status": "failed",
                "error_code": "AGENT_ERROR",
                "message": str(e),
            })
            await self.emitter.emit_done("任务失败")
