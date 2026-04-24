# src/services/content_summarizer.py
from typing import Optional
import asyncio
import logging

from src.services.llm_service import LLMService, get_llm_service
from src.services.memory_manager import MemoryManager
from src.models import (
    SummaryContent, ExtractedInfo, EventInfo, PersonInfo,
    TimeMarker, ThemeInfo, MemoryUpdatePlan, SessionState
)
from src.enums import PhaseType

logger = logging.getLogger(__name__)


class ContentSummarizer:
    """
    内容归纳服务
    
    职责：
    - 将对话内容归纳为结构化信息
    - 提取事件、人物、主题
    - 指导记忆库更新
    
    使用场景：
    - ConversationOrchestrator 异步调用
    - 触发时机：每轮对话后、阶段完成时、会话结束时
    
    调用LLMService：
    - 使用 "content_extraction" 模板
    - 结构化输出 ExtractedInfo
    """
    
    def __init__(
        self,
        llm_service: LLMService = None,
        memory_manager: MemoryManager = None,
    ):
        self.llm_service = llm_service or get_llm_service()
        self.memory_manager = memory_manager
    
    async def summarize_async(
        self,
        user_input: str,
        turn_id: int,
        session_id: str,
    ) -> Optional[SummaryContent]:
        """
        异步归纳（不阻塞主流程）
        
        Args:
            user_input: 用户输入
            turn_id: 轮次ID
            session_id: 会话ID
            
        Returns:
            归纳结果
        """
        try:
            # 调用LLM提取结构化信息
            extracted_info, raw = await self.llm_service.invoke_structured(
                template_name="content_extraction",
                variables={
                    "user_input": user_input,
                    "turn_id": turn_id,
                },
                output_model=ExtractedInfo,
            )
            
            if extracted_info is None:
                logger.warning(f"Content extraction failed: {raw.error}")
                return None
            
            # 构建归纳结果
            summary = SummaryContent(
                summary_id=f"sum_{session_id}_{turn_id}",
                session_id=session_id,
                turn_range=(turn_id, turn_id),
                extracted_info=extracted_info,
                memory_updates=self._build_memory_update_plan(extracted_info),
            )
            
            # 如果有记忆管理器，立即应用更新
            if self.memory_manager:
                await self.memory_manager.apply_summary(summary)
            
            return summary
            
        except Exception as e:
            logger.error(f"Summarization error: {e}")
            return None
    
    def _build_memory_update_plan(self, info: ExtractedInfo) -> MemoryUpdatePlan:
        """构建记忆更新计划"""
        return MemoryUpdatePlan(
            short_term_updates={
                "last_event": info.events[0].title if info.events else None,
                "last_person": info.people[0].name if info.people else None,
            },
            long_term_files=[
                f"events/{e.event_id}.md" for e in info.events
            ] + [
                f"people/{p.person_id}.md" for p in info.people
            ],
            profile_updates={
                "recent_entities": [p.name for p in info.people[:3]],
            }
        )
    
    async def prepare_handoff(
        self,
        state: SessionState,
    ) -> SummaryContent:
        """
        准备交接归纳（会话结束时）
        
        Args:
            state: 会话状态
            
        Returns:
            完整的归纳结果
        """
        # 汇总所有已收集的事件和人物
        all_events = self.memory_manager.get_all_events() if self.memory_manager else []
        all_people = self.memory_manager.get_all_people() if self.memory_manager else []
        
        extracted = ExtractedInfo(
            events=all_events,
            people=all_people,
            time_markers=self._build_time_markers(all_events),
            themes=self._extract_themes(all_events),
        )
        
        return SummaryContent(
            summary_id=f"sum_{state.session_id}_final",
            session_id=state.session_id,
            turn_range=(1, state.turn_count),
            extracted_info=extracted,
            memory_updates=MemoryUpdatePlan(),
            handoff_ready=True,
            handoff_reason="session_terminated",
        )
    
    def _build_time_markers(self, events: list) -> list:
        """构建时间标记"""
        markers = {}
        for event in events:
            time = event.time
            if time not in markers:
                markers[time] = TimeMarker(
                    time=time,
                    events=[],
                    phase=self._determine_phase(time),
                )
            markers[time].events.append(event.event_id)
        return list(markers.values())
    
    def _determine_phase(self, time_str: str) -> str:
        """根据时间确定阶段"""
        # 简化实现
        return "unknown"
    
    def _extract_themes(self, events: list) -> list:
        """提取主题"""
        themes = {}
        for event in events:
            if event.significance:
                theme = event.significance[:20]
                if theme not in themes:
                    themes[theme] = ThemeInfo(
                        theme=theme,
                        related_events=[],
                        description=event.significance,
                    )
                themes[theme].related_events.append(event.event_id)
        return list(themes.values())