"""Story generation runner — wraps StoryGenerationAgent for SSE streaming."""

from pathlib import Path

from src.agents.story_generation_agent import (
    LIFE_STAGE_LABELS,
    REQUIRED_EVENT_COUNT,
    StoryGenerationAgent,
    StoryOutputInvalidError,
    StoryStateSaveError,
)
from src.config.llm_config import get_default_config
from src.service.agent_runners.base_runner import BaseAgentRunner
from src.services.llm_service import LLMService
from src.services.observability import observability_context, observe_step


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
            with observability_context(self.build_trace_context(
                agent="story_generation",
                operation="generate",
            )):
                agent = self._create_agent(kb_path)

                await self.emitter.emit("task_started", {
                    "user_id": self.user_id,
                    "required_event_count": REQUIRED_EVENT_COUNT,
                    "mode": "life_stage_batches",
                })

                with observe_step("story_generation.scan_events", as_type="tool"):
                    events = agent.load_unconsumed_events()

                available_count = len(events)
                ready_stage_events = agent.select_ready_stage_events(events)
                ready_stages = list(ready_stage_events.keys())
                await self.emitter.emit("scanning", {
                    "step": "scanning",
                    "message": f"扫描到 {available_count} 个未生成故事的事件，{len(ready_stages)} 个时期已满足生成条件",
                    "available_events": available_count,
                    "required_events": REQUIRED_EVENT_COUNT,
                    "ready_life_stages": ready_stages,
                })

                if not ready_stage_events:
                    await self.emitter.emit("failed", {
                        "status": "failed",
                        "error_code": "INSUFFICIENT_EVENTS",
                        "message": "没有任何时期达到15个未生成故事的事件",
                        "required_events": REQUIRED_EVENT_COUNT,
                    })
                    await self.emitter.emit_done("任务失败")
                    return

                saved_stories = []
                failed_stages = []
                consumed_count = 0

                for life_stage, selected_events in ready_stage_events.items():
                    stage_label = LIFE_STAGE_LABELS.get(life_stage, life_stage)
                    await self.emitter.emit("generating", {
                        "step": "generating",
                        "message": f"正在根据{stage_label}最早的 15 个事件生成故事...",
                        "life_stage": life_stage,
                        "life_stage_label": stage_label,
                        "selected_event_count": len(selected_events),
                        "selected_event_paths": [event.path for event in selected_events],
                    })

                    try:
                        story = await agent.generate_story(selected_events, life_stage=life_stage)

                        with observe_step("story_generation.save_story", as_type="tool"):
                            saved = agent.save_story_and_mark_consumed(
                                story,
                                selected_events,
                                life_stage=life_stage,
                            )
                    except StoryStateSaveError as e:
                        failed_stages.append({
                            "life_stage": life_stage,
                            "life_stage_label": stage_label,
                            "error_code": "STATE_SAVE_FAILED",
                            "message": str(e),
                            "story_path": e.story_path,
                        })
                        await self.emitter.emit("stage_failed", failed_stages[-1])
                        continue
                    except StoryOutputInvalidError as e:
                        failed_stages.append({
                            "life_stage": life_stage,
                            "life_stage_label": stage_label,
                            "error_code": "STORY_GENERATION_FAILED",
                            "message": str(e),
                        })
                        await self.emitter.emit("stage_failed", failed_stages[-1])
                        continue
                    except Exception as e:
                        failed_stages.append({
                            "life_stage": life_stage,
                            "life_stage_label": stage_label,
                            "error_code": "AGENT_ERROR",
                            "message": str(e),
                        })
                        await self.emitter.emit("stage_failed", failed_stages[-1])
                        continue

                    consumed_count += len(saved.event_paths)
                    saved_payload = {
                        "step": "saved",
                        "message": f"{stage_label}故事已保存，事件消费状态已更新",
                        "story_id": saved.story_id,
                        "story_path": saved.story_path,
                        "life_stage": saved.life_stage,
                        "life_stage_label": stage_label,
                        "consumed_event_count": len(saved.event_paths),
                    }
                    saved_stories.append(saved_payload)
                    await self.emitter.emit("saved", saved_payload)

                remaining_count = available_count - consumed_count
                if saved_stories:
                    status = "partial_completed" if failed_stages else "completed"
                    first_story = saved_stories[0]
                    await self.emitter.emit("completed", {
                        "status": status,
                        "story_id": first_story.get("story_id"),
                        "story_path": first_story.get("story_path"),
                        "life_stage": first_story.get("life_stage"),
                        "life_stage_label": first_story.get("life_stage_label"),
                        "stories": saved_stories,
                        "failed_stages": failed_stages,
                        "generated_story_count": len(saved_stories),
                        "consumed_event_count": consumed_count,
                        "remaining_event_count": remaining_count,
                    })
                    done_message = "故事部分生成完成" if failed_stages else "故事生成完成"
                    await self.emitter.emit_done(done_message)
                    return

                await self.emitter.emit("failed", {
                    "status": "failed",
                    "error_code": "STORY_GENERATION_FAILED",
                    "message": "所有满足条件的时期都生成失败",
                    "failed_stages": failed_stages,
                })
                await self.emitter.emit_done("任务失败")

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
