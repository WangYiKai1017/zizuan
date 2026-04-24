from typing import Dict, List, Any, Optional
import asyncio
import logging

from src.storage.memory_repository import MemoryRepository
from src.services.llm_service import LLMService, get_llm_service
from src.models import (
    EventInfo, PersonInfo, SummaryContent,
    ConversationTurn, SessionState,
    OrganizedMemory, TimelineUpdate, EventExtract, PersonExtract, ProfileUpdates
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
        # 1. 格式化输入变量
        variables = {
            "conversation_content": self._format_conversation_content(turns),
            "existing_timeline": self._format_existing_timeline(),
            "existing_people": self._format_existing_people(),
            "current_phase": PHASE_LABELS.get(current_phase, str(current_phase)),
        }
        
        # 2. 调用 LLM 整理
        result, raw = await self.llm_service.invoke_structured(
            template_name="memory_organization",
            variables=variables,
            output_model=OrganizedMemory,
        )
        
        if result is None:
            logger.error(f"Memory organization failed: {raw.error}")
            return OrganizedMemory.empty()
        
        logger.info(f"Memory organized: {len(result.events)} events, {len(result.people)} people")
        
        # 3. 按整理结果存储
        await self._apply_organized_memory(result)
        
        return result
    
    async def _apply_organized_memory(self, memory: OrganizedMemory) -> Dict[str, str]:
        """
        应用整理结果到存储
        
        Args:
            memory: 整理后的结构化记忆
            
        Returns:
            创建的文件路径字典
        """
        results = {"events": [], "people": [], "timeline": []}
        
        # 并行保存
        tasks = []
        
        # 保存事件（同时更新时间线）
        for event in memory.events:
            event_info = self._convert_to_event_info(event)
            tasks.append(self._save_event_with_timeline_update(event_info, memory.timeline_updates))
        
        # 保存人物
        for person in memory.people:
            person_info = self._convert_to_person_info(person)
            tasks.append(self.repository.save_person(person_info))
        
        if tasks:
            paths = await asyncio.gather(*tasks, return_exceptions=True)
            results["events"] = [p for p in paths[:len(memory.events)] if isinstance(p, str)]
            results["people"] = [p for p in paths[len(memory.events):] if isinstance(p, str)]
        
        # 更新画像记忆
        if memory.profile_updates:
            self._update_profile_from_memory(memory.profile_updates)
        
        logger.info(f"Applied memory: {len(results['events'])} events, {len(results['people'])} people saved")
        return results
    
    async def _save_event_with_timeline_update(
        self,
        event: EventInfo,
        timeline_updates: List[TimelineUpdate],
    ) -> str:
        """保存事件并更新时间线"""
        # 保存事件
        path = await self.repository.save_event(event)
        
        # 更新时间线文件
        for update in timeline_updates:
            if update.event_reference == event.event_id:
                await self.repository.update_timeline(event)
                break
        
        return path
    
    # ===== 格式化方法 =====
    
    def _format_conversation_content(self, turns: List[ConversationTurn]) -> str:
        """格式化对话内容"""
        lines = []
        for i, turn in enumerate(turns, 1):
            lines.append(f"### 第 {i} 轮")
            lines.append(f"时间：{turn.timestamp.strftime('%H:%M:%S')}")
            lines.append(f"用户：{turn.user_input}")
            if turn.agent_response:
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
    
    def _convert_to_event_info(self, event: EventExtract) -> EventInfo:
        """将 EventExtract 转换为 EventInfo"""
        return EventInfo(
            event_id=event.event_id,
            title=event.title,
            time=event.time or "",
            location=event.location or "",
            type=event.event_type.value if isinstance(event.event_type, EventType) else event.event_type,
            description=event.description,
            details=[],  # EventExtract没有details字段
            participants=event.participants,
            emotions=event.emotions,
            significance=event.user_evaluation or "",
            source_turns=event.source_turns,
        )
    
    def _convert_to_person_info(self, person: PersonExtract) -> PersonInfo:
        """将 PersonExtract 转换为 PersonInfo"""
        # 转换关系
        relationships = {rel.related_person_id: rel.relationship for rel in person.relationships}
        
        return PersonInfo(
            person_id=person.person_id,
            name=person.name,
            role=person.relation,
            description=person.description,
            relation_to_protagonist=person.relation,
            source_events=[],  # PersonExtract没有source_events字段
            birth_year=person.first_appear_time or "",
            characteristics=[person.personality] if person.personality else [],
            influence=person.influence_level.value if isinstance(person.influence_level, Importance) else person.influence_level,
            quotes=person.key_quotes,
        )
    
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
            results["files_created"] = list(paths.values())
            results["events_saved"] = len(summary.extracted_info.events)
            results["people_saved"] = len(summary.extracted_info.people)
        
        # 更新画像记忆
        self.update_profile(summary.extracted_info)
        
        logger.info(f"Applied summary: {results}")
        return results
    
    def clear_session(self) -> None:
        """清空会话相关记忆（保留长期记忆）"""
        self.repository.clear_short_term()