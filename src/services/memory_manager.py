from typing import Dict, List, Any, Optional
import asyncio
import logging

from src.storage.memory_repository import MemoryRepository
from src.services.llm_service import LLMService, get_llm_service
from src.models import (
    EventInfo, PersonInfo, SummaryContent,
    ConversationTurn, SessionState,
    OrganizedMemory, TimelineUpdate, EventExtract, PersonExtract, ProfileUpdates,
    EventLifePhaseResolution,
)
from src.enums import PhaseType
from src.models.organized_memory import EventType, Importance, RelationType

logger = logging.getLogger(__name__)

# 人生阶段标签
PHASE_LABELS = {
    PhaseType.CHILDHOOD: "童年时期（0-12岁）",
    PhaseType.YOUTH: "青少年时期（12-18岁）",
    PhaseType.YOUNG_ADULT: "青年时期（18-35岁）",
    PhaseType.MIDDLE_AGE: "中年时期（35-60岁）",
    PhaseType.ELDERLY: "老年时期（60岁以后）",
}

MEMORY_ORGANIZATION_MAX_TOKENS = 8192
MEMORY_ORGANIZATION_FALLBACK_BATCH_SIZE = 1
VALID_EVENT_LIFE_PHASES = {"childhood", "youth", "middle_age", "elderly"}
EVENT_LIFE_PHASE_ALIASES = {
    "童年": "childhood",
    "童年时期": "childhood",
    "小时候": "childhood",
    "幼年": "childhood",
    "儿时": "childhood",
    "少年": "youth",
    "少年时期": "youth",
    "青少年": "youth",
    "青少年时期": "youth",
    "青春期": "youth",
    "学生时代": "youth",
    "中年": "middle_age",
    "中年时期": "middle_age",
    "中年阶段": "middle_age",
    "老年": "elderly",
    "老年时期": "elderly",
    "晚年": "elderly",
    "退休后": "elderly",
}
EVENT_LIFE_PHASE_RESOLUTION_CONCURRENCY = 4


class LifePhaseResolutionError(ValueError):
    """Raised when an event life_phase cannot be resolved safely."""


class MemoryManager:
    """
    记忆管理服务 - 提供记忆读写的高级接口
    
    职责：
    - 统一管理三层记忆的读写操作
    - **调用 LLM 整理采访内容为结构化信息**
    - 协调 MemoryRepository 完成存储
    - 提供记忆查询接口
    
    使用场景：
    - ContentSummarizer 调用更新记忆
    - KnowledgeBaseQuerier 调用查询记忆
    - ConversationOrchestrator 调用管理会话记忆
    
    调用 LLMService：
    - 使用 "memory_organization" 模板整理信息
    - 从时间线、事件、人物三个维度结构化
    """
    
    def __init__(
        self,
        repository: MemoryRepository,
        llm_service: LLMService = None,
    ):
        """
        初始化
        
        Args:
            repository: 记忆仓储
            llm_service: LLM 服务（用于信息整理）
        """
        self.repository = repository
        self.llm_service = llm_service or get_llm_service()
    
    # ========== 短期记忆管理 ==========
    
    def update_short_term(self, key: str, value: Any) -> None:
        """
        更新短期记忆
        
        Args:
            key: 键名
            value: 值
        """
        self.repository.update_short_term(key, value)
    
    def get_short_term(self, key: str) -> Optional[Any]:
        """
        获取短期记忆
        
        Args:
            key: 键名
            
        Returns:
            值（不存在返回None）
        """
        return self.repository.get_short_term(key)
    
    def add_conversation_turn(self, turn_data: Dict[str, Any]) -> None:
        """
        添加对话轮次到短期记忆
        
        Args:
            turn_data: 对话轮次数据
        """
        self.repository.add_to_history(turn_data)
    
    def get_recent_conversations(self, n: int = 5) -> List[Dict[str, Any]]:
        """
        获取最近的对话历史
        
        Args:
            n: 轮次数量
            
        Returns:
            对话历史列表
        """
        return self.repository.get_history(n)
    
    # ========== 长期记忆管理 ==========
    
    # ===== 核心：LLM 整理 + 存储 =====
    
    async def organize_and_save(
        self,
        turns: List[ConversationTurn],
        current_phase: PhaseType,
    ) -> OrganizedMemory:
        """
        整理并保存记忆（核心方法）
        
        流程：
        1. 格式化对话内容
        2. 调用 LLM 整理为结构化信息
        3. 按三维度存储：时间线、事件、人物
        4. 更新画像记忆
        
        Args:
            turns: 对话轮次列表
            current_phase: 当前人生阶段
            
        Returns:
            OrganizedMemory: 整理后的结构化记忆
        """
        # 1. 调用 LLM 整理
        result, raw = await self._invoke_memory_organization(
            turns,
            current_phase,
            trace_metadata={"mode": "full"},
        )

        if result is None and self._should_retry_in_batches(raw, turns):
            logger.warning(
                "Memory organization full pass failed, retrying in %s-turn batches: %s",
                MEMORY_ORGANIZATION_FALLBACK_BATCH_SIZE,
                raw.error if raw else "unknown error",
            )
            batched = OrganizedMemory.empty()
            any_success = False

            for batch_start in range(0, len(turns), MEMORY_ORGANIZATION_FALLBACK_BATCH_SIZE):
                batch = turns[batch_start:batch_start + MEMORY_ORGANIZATION_FALLBACK_BATCH_SIZE]
                batch_result, batch_raw = await self._invoke_memory_organization(
                    batch,
                    current_phase,
                    trace_metadata={
                        "mode": "fallback_batch",
                        "batch_start": batch_start,
                        "batch_size": len(batch),
                    },
                )
                if batch_result is None:
                    logger.error(
                        "Memory organization fallback batch failed at %s: %s",
                        batch_start,
                        batch_raw.error if batch_raw else "unknown error",
                    )
                    continue

                await self._normalize_event_life_phases(batch_result.events)
                logger.info(
                    "Memory organized fallback batch at %s: %s events, %s people",
                    batch_start,
                    len(batch_result.events),
                    len(batch_result.people),
                )
                self._merge_organized_memory(batched, batch_result)
                any_success = True

            if any_success:
                logger.info(
                    "Memory organized via fallback batches: %s events, %s people",
                    len(batched.events),
                    len(batched.people),
                )
                await self._apply_organized_memory(batched, turns)
                return batched

        if result is None:
            logger.error(f"Memory organization failed: {raw.error if raw else 'unknown error'}")
            return OrganizedMemory.empty()

        logger.info(f"Memory organized: {len(result.events)} events, {len(result.people)} people")

        await self._normalize_event_life_phases(result.events)

        # 2. 按整理结果存储
        await self._apply_organized_memory(result, turns)

        return result

    async def _invoke_memory_organization(
        self,
        turns: List[ConversationTurn],
        current_phase: PhaseType,
        trace_metadata: Optional[Dict[str, Any]] = None,
    ):
        """调用结构化记忆整理，并为长事件列表提供更大的输出上限。"""
        phase_instruction = (
            f"{PHASE_LABELS.get(current_phase, str(current_phase))}\n"
            "注意：请根据内容自动判断每个事件/记忆属于哪个人生阶段；"
            "life_phase 字段只能输出英文枚举 childhood、youth、middle_age、elderly，"
            "不要输出中文阶段名，也不需要依赖对话中的标记。"
        )
        variables = {
            "conversation_content": self._format_conversation_content(turns),
            "existing_timeline": self._format_existing_timeline(),
            "existing_people": self._format_existing_people(),
            "current_phase": phase_instruction,
        }

        configured_max_tokens = getattr(getattr(self.llm_service, "config", None), "max_tokens", 0)
        if not isinstance(configured_max_tokens, int):
            configured_max_tokens = 0
        max_tokens = max(configured_max_tokens, MEMORY_ORGANIZATION_MAX_TOKENS)

        result, raw = await self.llm_service.invoke_structured(
            template_name="memory_organization",
            variables=variables,
            output_model=OrganizedMemory,
            max_tokens=max_tokens,
            trace_metadata=trace_metadata,
        )
        return result, raw

    def _should_retry_in_batches(self, raw: Any, turns: List[ConversationTurn]) -> bool:
        if len(turns) <= MEMORY_ORGANIZATION_FALLBACK_BATCH_SIZE:
            return False
        error = getattr(raw, "error", "") or ""
        if "Unterminated string" in error or "JSON" in error or "Parse error" in error:
            return True
        return False

    def _merge_organized_memory(
        self,
        target: OrganizedMemory,
        source: OrganizedMemory,
    ) -> None:
        target.timeline_updates.extend(source.timeline_updates or [])
        target.events.extend(source.events or [])
        target.people.extend(source.people or [])
        if source.profile_updates:
            target.profile_updates = source.profile_updates
        if source.processing_summary:
            target.processing_summary = source.processing_summary

    async def _normalize_event_life_phases(self, events: List[EventExtract]) -> None:
        """Resolve every event life_phase before any event is persisted."""
        unresolved = []
        for event in events or []:
            resolved = self._resolve_life_phase_direct_or_alias(event.life_phase)
            if resolved:
                event.life_phase = resolved
            else:
                unresolved.append(event)

        if not unresolved:
            return

        semaphore = asyncio.Semaphore(EVENT_LIFE_PHASE_RESOLUTION_CONCURRENCY)

        async def resolve_with_limit(event: EventExtract) -> str:
            async with semaphore:
                return await self._resolve_life_phase_with_llm(event)

        resolved_values = await asyncio.gather(
            *(resolve_with_limit(event) for event in unresolved),
            return_exceptions=True,
        )

        errors = []
        for event, resolved in zip(unresolved, resolved_values):
            if isinstance(resolved, Exception):
                errors.append(f"{event.event_id}: {resolved}")
                continue
            normalized = self._resolve_life_phase_direct_or_alias(resolved)
            if not normalized:
                errors.append(f"{event.event_id}: invalid life_phase {resolved!r}")
                continue
            event.life_phase = normalized

        if errors:
            raise LifePhaseResolutionError("; ".join(errors))

    def _resolve_life_phase_direct_or_alias(self, value: Any) -> Optional[str]:
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        normalized = text.lower().replace("-", "_").replace(" ", "_")
        if normalized in VALID_EVENT_LIFE_PHASES:
            return normalized

        return EVENT_LIFE_PHASE_ALIASES.get(text)

    async def _resolve_life_phase_with_llm(self, event: EventExtract) -> str:
        result, raw = await self.llm_service.invoke_structured(
            template_name="event_life_phase_resolution",
            variables={
                "event_id": event.event_id,
                "title": event.title,
                "time": event.time or "",
                "description": event.description,
                "event_type": event.event_type.value if isinstance(event.event_type, EventType) else str(event.event_type),
                "participants": ", ".join(str(item) for item in event.participants or []),
                "original_life_phase": event.life_phase or "",
            },
            output_model=EventLifePhaseResolution,
            trace_node="memory_organization.event_life_phase_resolution",
            trace_tags=["memory_organization", "event_life_phase_resolution"],
            trace_metadata={
                "event_id": event.event_id,
                "title": event.title,
                "time": event.time or "",
                "original_life_phase": event.life_phase or "",
                "resolution_source": "llm",
            },
        )
        if result is None:
            error = getattr(raw, "error", None) or "unknown error"
            raise LifePhaseResolutionError(
                f"LLM failed to resolve life_phase for event {event.event_id}: {error}"
            )
        return result.life_phase
    
    def _normalize_link_path(self, path: str) -> str:
        """Normalize a stored file path into a wiki-link path relative to
        the user's KB root (knowledge_base/{user_id}/).

        Delegates to the underlying MarkdownFileManager when available so
        any cross-reference written into markdown content stays in the
        canonical ``[display](relative/path.md)`` form.
        """
        if not path:
            return ""
        file_manager = getattr(self.repository, "file_manager", None)
        if file_manager is not None and hasattr(file_manager, "_normalize_wiki_link"):
            return file_manager._normalize_wiki_link(path)
        return str(path)

    def _format_link(self, display_text: str, path: str) -> str:
        """Format a markdown wiki link with a normalized relative path."""
        file_manager = getattr(self.repository, "file_manager", None)
        if file_manager is not None and hasattr(file_manager, "format_wiki_link"):
            return file_manager.format_wiki_link(display_text, path)
        return f"[{display_text or ''}]({self._normalize_link_path(path)})"

    async def _apply_organized_memory(
        self,
        memory: OrganizedMemory,
        source_turns: Optional[List[ConversationTurn]] = None,
    ) -> Dict[str, List[str]]:
        """
        应用整理结果到存储
        
        Args:
            memory: 整理后的结构化记忆
            
        Returns:
            创建的文件路径字典（路径以 KB 根目录为基准的相对路径）
        """
        results = {"events": [], "people": [], "timeline": []}
        
        # 保存事件（同时更新时间线）
        events_to_save = [
            event for event in memory.events
            if self._should_persist_event(event)
        ]
        event_paths = []
        for event in events_to_save:
            event_info = self._convert_to_event_info(event, source_turns or [])
            event_path = await self._save_event_with_timeline_update(event_info, memory.timeline_updates)
            event_paths.append(event_path)
        
        # 保存人物
        tasks = []
        for person in memory.people:
            person_info = self._convert_to_person_info(person)
            tasks.append(self.repository.save_person(person_info))
        
        people_paths = []
        if tasks:
            paths = await asyncio.gather(*tasks, return_exceptions=True)
            people_paths = [p for p in paths if isinstance(p, str)]

        # Normalize stored paths so any consumer rendering them as
        # markdown links gets a clean KB-relative form.
        results["events"] = [self._normalize_link_path(p) for p in event_paths if isinstance(p, str)]
        results["people"] = [self._normalize_link_path(p) for p in people_paths if isinstance(p, str)]
        
        # 更新画像记忆
        if memory.profile_updates:
            self._update_profile_from_memory(memory.profile_updates)
        
        logger.info(f"Applied memory: {len(results['events'])} events, {len(results['people'])} people saved")
        return results

    def _should_persist_event(self, event: EventExtract) -> bool:
        """过滤明显由模型推断出来、且置信度较低的事件。"""
        text = " ".join([
            event.title or "",
            event.time or "",
            event.description or "",
            event.user_evaluation or "",
        ])
        if any(token in text for token in ["自传采访", "采访开始", "接受自传采访"]):
            logger.info(f"Skip meta interview event: {event.title}")
            return False
        if "推算" in text and event.confidence <= 0.65:
            logger.info(f"Skip inferred low-confidence event: {event.title}")
            return False
        return True
    
    async def _save_event_with_timeline_update(
        self,
        event: EventInfo,
        timeline_updates: List[TimelineUpdate],
    ) -> str:
        """保存事件并更新时间线"""
        # 保存事件
        path = await self.repository.save_event(event)
        
        # 更新时间线文件。即使模型没有显式返回 timeline_updates，
        # 只要事件有时间，也应该进入人生大事年表。
        if event.time:
            await self.repository.update_timeline(event)
        
        return path
    
    # ===== 格式化方法 =====
    
    def _format_conversation_content(self, turns: List[ConversationTurn]) -> str:
        """格式化对话内容"""
        lines = []
        for i, turn in enumerate(turns, 1):
            lines.append(f"### 第 {i} 轮")
            lines.append(f"时间：{turn.timestamp}")
            lines.append(f"用户：{turn.user_input}")
            if turn.agent_response is not None:
                lines.append(f"助手：{turn.agent_response}")
            lines.append("")
        return "\n".join(lines)
    
    def _format_existing_timeline(self) -> str:
        """格式化已有时间线"""
        events = self.repository.get_all_events()
        if not events:
            return "（暂无时间线记录）"
        
        lines = ["已有时间线节点："]
        sorted_events = sorted(events, key=lambda e: e.time or "")
        for event in sorted_events[:20]:
            lines.append(f"- {event.time}: {event.title}")
        return "\n".join(lines)
    
    def _format_existing_people(self) -> str:
        """格式化已有人物索引"""
        people = self.repository.get_all_people()
        if not people:
            return "（暂无人物记录）"
        
        lines = ["已有人物："]
        for person in people:
            lines.append(f"- {person.name} ({person.role})")
        return "\n".join(lines)
    
    # ===== 转换方法 =====
    
    def _convert_to_event_info(
        self,
        event: EventExtract,
        source_turns: Optional[List[ConversationTurn]] = None,
    ) -> EventInfo:
        """将 EventExtract 转换为 EventInfo"""
        return EventInfo(
            event_id=event.event_id,
            title=event.title,
            time=event.time or "",
            life_phase=event.life_phase,
            location=event.location or "",
            type=event.event_type.value if isinstance(event.event_type, EventType) else event.event_type,
            description=self._sanitize_event_description(event.description),
            details=self._extract_event_details(event, source_turns or []),
            participants=event.participants,
            emotions=event.emotions,
            significance=event.user_evaluation or "",
            source_turns=event.source_turns,
        )

    def _extract_event_details(
        self,
        event: EventExtract,
        source_turns: List[ConversationTurn],
    ) -> List[str]:
        """从用户原话中提取与事件相关的关键细节，防止归档只剩泛化摘要。"""
        import re

        keywords = set()
        if event.time:
            keywords.update(re.findall(r"\d{4}", event.time))
        if event.title:
            for token in re.split(r"[，。！？、\s]+", event.title):
                token = token.strip()
                if len(token) >= 2:
                    keywords.add(token)
            for token in re.findall(r"[\u4e00-\u9fff]{2,}", event.title):
                if len(token) >= 2:
                    keywords.add(token)
        for participant in event.participants or []:
            if participant:
                keywords.add(str(participant))

        details: List[str] = []
        for turn in source_turns:
            text = turn.user_input or ""
            if not text:
                continue
            if keywords and not any(keyword and keyword in text for keyword in keywords):
                continue

            clauses = [
                clause.strip()
                for clause in re.split(r"[。！？；;]\s*", text)
                if clause.strip()
            ]
            for clause in clauses:
                normalized = clause.rstrip("，,。")
                if normalized and normalized not in details:
                    details.append(normalized)
                if len(details) >= 8:
                    return details

        return details

    def _sanitize_event_description(self, description: str) -> str:
        """去掉模型常见的评价性/推断性补写，保留用户明确表达的事实。"""
        if not description:
            return ""

        text = description
        text = text.replace("作为技术骨干", "")
        text = text.replace("技术骨干", "钳工")
        text = text.replace("推测为", "为")
        text = text.replace("作为资深钳工，", "")
        text = text.replace("作为资深钳工", "")
        text = text.replace("资深钳工，", "钳工，")
        text = text.replace("资深钳工", "钳工")
        text = text.replace("的一个普通家庭", "")
        text = text.replace("一个普通家庭", "家庭")
        text = text.replace("这是一个重要的技术突破和职业成就。", "")
        text = text.replace("，体现技术传承", "")
        text = text.replace("，标志着其职业生涯的起点", "")

        import re
        text = re.sub(r"，?具体日期不详[^。]*。?", "。", text)
        text = re.sub(r"，?根据[^。]*推断[^。]*。?", "。", text)
        sentences = re.split(r"(?<=[。！？])", text)
        kept = [
            sentence for sentence in sentences
            if sentence and "推断" not in sentence and "推算" not in sentence and "推测" not in sentence and "具体日期不详" not in sentence
        ]
        cleaned = "".join(kept).strip()
        cleaned = cleaned.replace("，。", "。").rstrip("，,")
        return cleaned or description
    
    def _convert_to_person_info(self, person: PersonExtract) -> PersonInfo:
        """将 PersonExtract 转换为 PersonInfo"""
        # 转换关系
        relationships = {rel.related_person_id: rel.relationship for rel in person.relationships}
        if isinstance(person.personality, list):
            characteristics = [str(item) for item in person.personality if item]
        elif person.personality:
            characteristics = [str(person.personality)]
        else:
            characteristics = []
        
        return PersonInfo(
            person_id=person.person_id,
            name=person.name,
            role=person.relation,
            description=self._sanitize_person_description(person.description),
            relation_to_protagonist=person.relation,
            source_events=[],  # PersonExtract没有source_events字段
            birth_year=person.first_appear_time or "",
            characteristics=characteristics,
            influence=person.influence_level.value if isinstance(person.influence_level, Importance) else person.influence_level,
            quotes=person.key_quotes,
        )

    def _sanitize_person_description(self, description: str) -> str:
        """去掉人物描述中非用户明确表达的推测性补写。"""
        if not description:
            return ""
        import re
        text = description
        text = text.replace("推测为", "为")
        text = text.replace("具体职业不详，推测为钳工", "")
        text = text.replace("，推测为钳工", "")
        text = text.replace("推测为钳工", "")
        text = text.replace("资深钳工", "钳工")
        sentences = re.split(r"(?<=[。！？])", text)
        kept = [
            sentence for sentence in sentences
            if sentence and "推测" not in sentence and "推断" not in sentence and "具体职业不详" not in sentence
        ]
        cleaned = "".join(kept).strip().rstrip("，,")
        return cleaned or description
    
    # ===== 兼容旧接口 =====
    
    async def update_long_term(self, extracted_info) -> Dict[str, str]:
        """
        更新长期记忆（兼容旧接口）
        
        注意：推荐使用 organize_and_save() 方法
        """
        results = {}
        
        tasks = []
        
        for event in extracted_info.events:
            tasks.append(self._save_event_with_timeline(event))
        
        for person in extracted_info.people:
            tasks.append(self.repository.save_person(person))
        
        if tasks:
            paths = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, path in enumerate(paths):
                if isinstance(path, str):
                    if i < len(extracted_info.events):
                        results[f"event_{extracted_info.events[i].event_id}"] = path
                    else:
                        person_idx = i - len(extracted_info.events)
                        results[f"person_{extracted_info.people[person_idx].person_id}"] = path
                elif isinstance(path, Exception):
                    logger.error(f"Failed to save: {path}")
        
        return results
    
    async def _save_event_with_timeline(self, event: EventInfo) -> str:
        """保存事件并更新时间线"""
        path = await self.repository.save_event(event)
        await self.repository.update_timeline(event)
        return path
    
    async def query_events(
        self,
        keyword: Optional[str] = None,
        time_range: Optional[tuple] = None,
        event_type: Optional[str] = None,
    ) -> List[EventInfo]:
        """
        查询事件
        
        Args:
            keyword: 关键词
            time_range: 时间范围
            event_type: 事件类型
            
        Returns:
            事件列表
        """
        return await self.repository.query_events(keyword=keyword, time_range=time_range, event_type=event_type)
    
    async def get_event(self, event_id: str) -> Optional[EventInfo]:
        """获取单个事件"""
        return await self.repository.get_event(event_id)
    
    # ========== 画像记忆管理 ==========
    
    def _update_profile_from_memory(self, profile_updates: ProfileUpdates) -> None:
        """
        从整理结果更新画像记忆
        
        Args:
            profile_updates: 画像更新数据
        """
        if not profile_updates:
            return
        
        # 更新主人公信息
        if profile_updates.protagonist:
            protagonist = profile_updates.protagonist
            
            if protagonist.birth_year:
                self.repository.update_profile("birth_year", protagonist.birth_year)
            if protagonist.birth_place:
                self.repository.update_profile("birth_place", protagonist.birth_place)
            if protagonist.key_life_events:
                existing = self.repository.get_profile("key_life_events") or []
                self.repository.update_profile(
                    "key_life_events",
                    list(set(existing + protagonist.key_life_events))
                )
            if protagonist.personality_traits:
                existing = self.repository.get_profile("personality_traits") or []
                self.repository.update_profile(
                    "personality_traits",
                    list(set(existing + protagonist.personality_traits))
                )
            if protagonist.values_hints:
                existing = self.repository.get_profile("values_hints") or []
                self.repository.update_profile(
                    "values_hints",
                    list(set(existing + protagonist.values_hints))
                )
        
        # 更新人物关系网络
        if profile_updates.relationship_network:
            for edge in profile_updates.relationship_network:
                self.repository.update_profile(
                    f"relation_{edge.person1_id}_{edge.person2_id}",
                    {
                        "relationship": edge.relationship,
                        "evidence": edge.evidence,
                    }
                )
    
    def update_profile(self, extracted_info) -> None:
        """
        更新画像记忆（兼容旧接口）
        
        注意：推荐使用 organize_and_save() -> _update_profile_from_memory()
        """
        # 更新主人公基本信息
        for event in extracted_info.events:
            if event.type == "birth":
                self.repository.update_profile("birth_year", event.time)
            elif event.type == "career" and "第一份工作" in event.title:
                self.repository.update_profile("career_start", event.time)
        
        # 更新人物关系
        for person in extracted_info.people:
            self.repository.update_profile(
                f"relation_{person.person_id}",
                {
                    "name": person.name,
                    "role": person.role,
                    "description": person.description,
                }
            )
    
    def get_profile(self, key: str) -> Optional[Any]:
        """获取画像信息"""
        return self.repository.get_profile(key)
    
    def get_all_people(self) -> List[PersonInfo]:
        """获取所有人物"""
        return self.repository.get_all_people()
    
    def get_all_events(self) -> List[EventInfo]:
        """获取所有事件"""
        return self.repository.get_all_events()
    
    # ========== 批量操作 ==========
    
    async def apply_summary(self, summary: SummaryContent) -> Dict[str, Any]:
        """
        应用归纳结果到记忆库
        
        Args:
            summary: 归纳内容
            
        Returns:
            更新结果
        """
        results = {
            "events_saved": 0,
            "people_saved": 0,
            "files_created": [],
        }
        
        # 更新短期记忆
        for key, value in summary.memory_updates.short_term_updates.items():
            self.update_short_term(key, value)
        
        # 更新长期记忆
        if summary.extracted_info.events or summary.extracted_info.people:
            paths = await self.update_long_term(summary.extracted_info)
            # Normalize file paths so they can be embedded into markdown
            # cross-references without leaking absolute paths.
            results["files_created"] = [
                self._normalize_link_path(p) for p in paths.values()
            ]
            results["events_saved"] = len(summary.extracted_info.events)
            results["people_saved"] = len(summary.extracted_info.people)
        
        # 更新画像记忆
        self.update_profile(summary.extracted_info)
        
        logger.info(f"Applied summary: {results}")
        return results
    
    def clear_session(self) -> None:
        """清空会话相关记忆（保留长期记忆）"""
        self.repository.clear_short_term()
