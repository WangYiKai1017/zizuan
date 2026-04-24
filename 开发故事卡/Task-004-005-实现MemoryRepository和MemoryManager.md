# 开发故事卡 - Task 4-5: 实现MemoryRepository和MemoryManager

> 任务编号：Task-004/005  
> 优先级：P0  
> 依赖：Task-001, Task-003  
> 预计工时：1天

---

## 一、任务概述

实现记忆管理的核心组件：
- **MemoryRepository**：记忆仓储，统一管理三层记忆的存储
- **MemoryManager**：记忆管理服务，提供记忆读写的高级接口

---

## 二、项目上下文

### 2.1 三层记忆架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           三层记忆架构                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   短期记忆 (Short-Term Memory)                                          │
│   ─────────────────────────────────────────────────────────────────    │
│   • 存储：当前对话上下文                                                 │
│   • 容量：最近 10-20 轮对话                                             │
│   • 更新：每轮对话实时更新                                               │
│   • 用途：保持对话连贯性、避免重复提问                                    │
│   • 实现：内存字典 + LRU缓存                                            │
│                                                                         │
│   长期记忆 (Long-Term Memory)                                           │
│   ─────────────────────────────────────────────────────────────────    │
│   • 存储：已收集的事件、人物、时间线                                     │
│   • 格式：Markdown文件系统                                              │
│   • 更新：内容归纳后写入                                                │
│   • 用途：知识库检索、上下文引用                                         │
│   • 实现：MarkdownFileManager                                           │
│                                                                         │
│   画像记忆 (Profile Memory)                                             │
│   ─────────────────────────────────────────────────────────────────    │
│   • 存储：结构化的人物画像和关系网络                                     │
│   • 用途：供大模型发散联想、深度挖掘                                     │
│   • 更新：事件确认后更新画像                                            │
│   • 实现：JSON + Markdown混合                                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 三、详细设计

### 3.1 MemoryRepository（记忆仓储）

```python
# src/storage/memory_repository.py
from typing import Dict, List, Any, Optional
from collections import OrderedDict
from datetime import datetime
import json
from pydantic import BaseModel
import logging

from storage.markdown_file_manager import MarkdownFileManager
from models import EventInfo, PersonInfo

logger = logging.getLogger(__name__)


class LRUCache:
    """LRU缓存实现"""
    
    def __init__(self, capacity: int = 100):
        self.capacity = capacity
        self.cache: OrderedDict[str, Any] = OrderedDict()
    
    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None
    
    def put(self, key: str, value: Any) -> None:
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
    
    def clear(self) -> None:
        self.cache.clear()


class MemoryRepository:
    """
    记忆仓储 - 统一管理三层记忆的存储
    
    职责：
    - 管理短期记忆（内存缓存）
    - 管理长期记忆（文件系统）
    - 管理画像记忆（结构化存储）
    
    使用场景：
    - MemoryManager 的底层存储
    - KnowledgeBaseQuerier 的数据源
    """
    
    def __init__(
        self,
        file_manager: MarkdownFileManager,
        short_term_capacity: int = 20,
        cache_capacity: int = 100,
    ):
        """
        初始化
        
        Args:
            file_manager: Markdown文件管理器
            short_term_capacity: 短期记忆容量
            cache_capacity: 缓存容量
        """
        self.file_manager = file_manager
        
        # 短期记忆（内存）
        self._short_term: Dict[str, Any] = {}
        self._short_term_history: List[Dict[str, Any]] = []
        self._short_term_capacity = short_term_capacity
        
        # 缓存
        self._cache = LRUCache(cache_capacity)
        
        # 画像记忆（内存索引）
        self._profile_index: Dict[str, PersonInfo] = {}
        self._event_index: Dict[str, EventInfo] = {}
    
    # ========== 短期记忆 ==========
    
    def update_short_term(self, key: str, value: Any) -> None:
        """更新短期记忆"""
        self._short_term[key] = {
            "value": value,
            "timestamp": datetime.now().isoformat(),
        }
    
    def get_short_term(self, key: str) -> Optional[Any]:
        """获取短期记忆"""
        entry = self._short_term.get(key)
        return entry["value"] if entry else None
    
    def add_to_history(self, turn_data: Dict[str, Any]) -> None:
        """添加对话历史到短期记忆"""
        self._short_term_history.append(turn_data)
        
        # 保持容量限制
        if len(self._short_term_history) > self._short_term_capacity:
            self._short_term_history.pop(0)
    
    def get_history(self, n: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取对话历史"""
        if n:
            return self._short_term_history[-n:]
        return self._short_term_history.copy()
    
    def clear_short_term(self) -> None:
        """清空短期记忆"""
        self._short_term.clear()
        self._short_term_history.clear()
    
    # ========== 长期记忆 ==========
    
    async def save_event(self, event: EventInfo) -> str:
        """
        保存事件到长期记忆
        
        Args:
            event: 事件信息
            
        Returns:
            文件路径
        """
        # 确定存储目录
        phase_dir = self._get_phase_directory(event.time)
        file_name = self._generate_event_filename(event.title)
        relative_path = f"events/{phase_dir}/{file_name}.md"
        
        # 转换为Markdown并保存
        content = event.to_markdown()
        path = await self.file_manager.create_file(relative_path, content, overwrite=True)
        
        # 更新索引
        self._event_index[event.event_id] = event
        self._cache.put(f"event:{event.event_id}", event)
        
        logger.info(f"Saved event: {event.event_id} to {path}")
        return path
    
    async def save_person(self, person: PersonInfo) -> str:
        """
        保存人物到画像记忆
        
        Args:
            person: 人物信息
            
        Returns:
            文件路径
        """
        # 确定存储目录
        role_dir = self._get_role_directory(person.role)
        file_name = self._sanitize_filename(person.name)
        relative_path = f"people/{role_dir}/{file_name}.md"
        
        # 转换为Markdown并保存
        content = person.to_markdown()
        path = await self.file_manager.create_file(relative_path, content, overwrite=True)
        
        # 更新索引
        self._profile_index[person.person_id] = person
        self._cache.put(f"person:{person.person_id}", person)
        
        logger.info(f"Saved person: {person.person_id} to {path}")
        return path
    
    async def get_event(self, event_id: str) -> Optional[EventInfo]:
        """获取事件"""
        # 先查缓存
        cached = self._cache.get(f"event:{event_id}")
        if cached:
            return cached
        
        # 查索引
        return self._event_index.get(event_id)
    
    async def get_person(self, person_id: str) -> Optional[PersonInfo]:
        """获取人物"""
        # 先查缓存
        cached = self._cache.get(f"person:{person_id}")
        if cached:
            return cached
        
        # 查索引
        return self._profile_index.get(person_id)
    
    async def update_timeline(self, event: EventInfo) -> None:
        """更新时间线文件"""
        timeline_path = "timeline/life-events.md"
        
        # 时间线条目
        entry = f"""
## {event.time}
- **事件**: {event.title}
- **类型**: {event.type}
- **详情**: [[../events/{self._get_phase_directory(event.time)}/{self._generate_event_filename(event.title)}.md|查看详情]]
"""
        
        await self.file_manager.update_file(timeline_path, entry, append=True)
    
    async def query_events(
        self,
        keyword: Optional[str] = None,
        time_range: Optional[tuple] = None,
        event_type: Optional[str] = None,
    ) -> List[EventInfo]:
        """查询事件"""
        results = []
        
        # 如果有索引，先从索引查
        for event in self._event_index.values():
            match = True
            
            if keyword and keyword.lower() not in event.title.lower() and keyword.lower() not in event.description.lower():
                match = False
            
            if event_type and event.type != event_type:
                match = False
            
            if match:
                results.append(event)
        
        return results
    
    # ========== 画像记忆 ==========
    
    def update_profile(self, key: str, value: Any) -> None:
        """更新画像记忆"""
        self._short_term[f"profile:{key}"] = value
    
    def get_profile(self, key: str) -> Optional[Any]:
        """获取画像记忆"""
        return self._short_term.get(f"profile:{key}", {}).get("value")
    
    def get_all_people(self) -> List[PersonInfo]:
        """获取所有人物"""
        return list(self._profile_index.values())
    
    def get_all_events(self) -> List[EventInfo]:
        """获取所有事件"""
        return list(self._event_index.values())
    
    # ========== 工具方法 ==========
    
    def _get_phase_directory(self, time_str: str) -> str:
        """根据时间确定人生阶段目录"""
        # 简化实现：根据关键词判断
        # 实际应该根据具体年份计算
        time_lower = time_str.lower()
        
        if any(kw in time_lower for kw in ["童年", "小时候", "出生"]):
            return "childhood"
        elif any(kw in time_lower for kw in ["少年", "学生", "中学"]):
            return "youth"
        elif any(kw in time_lower for kw in ["青年", "工作", "结婚"]):
            return "middle_age"
        else:
            return "elderly"
    
    def _get_role_directory(self, role: str) -> str:
        """根据角色确定目录"""
        if role in ["父亲", "母亲", "配偶", "子女"]:
            return "family"
        elif role in ["朋友", "邻居"]:
            return "friends"
        elif role in ["同事", "上司", "下属"]:
            return "colleagues"
        else:
            return "others"
    
    def _generate_event_filename(self, title: str) -> str:
        """生成事件文件名"""
        # 简化：使用标题的拼音或英文
        import re
        name = re.sub(r'[^\w\u4e00-\u9fff]', '-', title)
        return name[:50]  # 限制长度
    
    def _sanitize_filename(self, name: str) -> str:
        """清理文件名"""
        import re
        return re.sub(r'[^\w\u4e00-\u9fff]', '-', name)[:50]
```

### 3.2 MemoryManager（记忆管理服务）- 含 LLM 整理

**核心变化**：保存和更新记忆前，先调用大模型进行信息整理。

```python
# src/services/memory_manager.py
from typing import Dict, List, Any, Optional
import asyncio
import logging

from storage.memory_repository import MemoryRepository
from services.llm_service import LLMService, get_llm_service
from models import (
    EventInfo, PersonInfo, SummaryContent,
    ConversationTurn, SessionState,
    OrganizedMemory, TimelineUpdate, EventExtract, PersonExtract, ProfileUpdates
)
from enums import PhaseType, EventType, Importance, RelationType

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
            time=event.time,
            location=event.location,
            type=event.event_type.value if isinstance(event.event_type, EventType) else event.event_type,
            description=event.description,
            participants=event.participants,
            emotions=event.emotions,
            user_evaluation=event.user_evaluation,
            related_events=event.related_events,
            source_turns=event.source_turns,
            confidence=event.confidence,
        )
    
    def _convert_to_person_info(self, person: PersonExtract) -> PersonInfo:
        """将 PersonExtract 转换为 PersonInfo"""
        relationships = {}
        for rel in person.relationships:
            relationships[rel.related_person_id] = rel.relationship
        
        return PersonInfo(
            person_id=person.person_id,
            name=person.name,
            role=person.relation,
            description=person.description,
            appearance=person.appearance,
            personality=person.personality,
            occupation=person.occupation,
            key_quotes=person.key_quotes,
            relationships=relationships,
            influence_level=person.influence_level.value if isinstance(person.influence_level, InfluenceLevel) else person.influence_level,
            source_turns=person.source_turns,
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
        return await self.repository.query_events(keyword, time_range, event_type)
    
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
```

---

## 四、开发要求

### 4.1 代码规范

```python
# 1. 使用async/await处理文件操作
async def save_event(self, event: EventInfo) -> str:
    path = await self.file_manager.create_file(...)

# 2. 并行操作使用asyncio.gather
paths = await asyncio.gather(
    self.repository.save_event(event1),
    self.repository.save_event(event2),
)

# 3. 缓存命中要更新访问顺序
def get(self, key: str) -> Optional[Any]:
    if key in self.cache:
        self.cache.move_to_end(key)  # LRU
        return self.cache[key]
```

### 4.2 单元测试要求

```python
# tests/test_memory_repository.py
import pytest
from storage.memory_repository import MemoryRepository, LRUCache
from storage.markdown_file_manager import MarkdownFileManager
from models import EventInfo, PersonInfo

class TestLRUCache:
    def test_put_and_get(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        assert cache.get("a") == 1
    
    def test_capacity(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)  # a should be evicted
        assert cache.get("a") is None

class TestMemoryRepository:
    @pytest.fixture
    async def repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(tmpdir)
            yield MemoryRepository(fm)
    
    @pytest.mark.asyncio
    async def test_save_event(self, repository):
        event = EventInfo(
            event_id="e001",
            title="测试事件",
            time="1970年",
            description="这是一个测试事件",
        )
        
        path = await repository.save_event(event)
        assert path is not None
    
    def test_short_term_memory(self, repository):
        repository.update_short_term("test", "value")
        assert repository.get_short_term("test") == "value"
```

### 4.3 验收标准

- [ ] MemoryRepository实现完成
- [ ] MemoryManager实现完成
- [ ] LRU缓存正常工作
- [ ] 三层记忆读写正常
- [ ] 并行保存正常工作
- [ ] 单元测试覆盖率 > 80%

---

## 五、新增数据模型

### 5.1 OrganizedMemory 及相关模型

由于引入 LLM 整理环节，需要在 `src/models/` 目录下新增以下数据模型：

```python
# src/models/organized_memory.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

class TimeType(str, Enum):
    EXACT = "exact"           # 精确时间
    APPROXIMATE = "approximate"  # 大约时间
    PERIOD = "period"         # 时间段
    UNKNOWN = "unknown"       # 时间不详

class EventType(str, Enum):
    BIRTH = "birth"
    FAMILY = "family"
    EDUCATION = "education"
    CAREER = "career"
    MARRIAGE = "marriage"
    CHILDREN = "children"
    ACHIEVEMENT = "achievement"
    DIFFICULTY = "difficulty"
    MIGRATION = "migration"
    OTHER = "other"

class Importance(str, Enum):
    CORE = "core"        # 核心事件（人生转折点）
    IMPORTANT = "important"
    NORMAL = "normal"

class RelationType(str, Enum):
    FAMILY = "family"
    FRIEND = "friend"
    COLLEAGUE = "colleague"
    NEIGHBOR = "neighbor"
    TEACHER = "teacher"
    STUDENT = "student"
    OTHER = "other"

class InfluenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

# 时间线更新
class TimelineUpdate(BaseModel):
    time_point: str
    time_type: TimeType
    life_phase: str
    event_reference: Optional[str] = None
    significance: Optional[str] = None

# 事件提取
class EventExtract(BaseModel):
    event_id: str
    title: str
    time: Optional[str] = None
    location: Optional[str] = None
    event_type: EventType
    importance: Importance
    description: str
    participants: List[str] = Field(default_factory=list)
    emotions: List[str] = Field(default_factory=list)
    user_evaluation: Optional[str] = None
    related_events: List[str] = Field(default_factory=list)
    source_turns: List[int] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)

# 人物关系
class PersonRelationship(BaseModel):
    related_person_id: str
    relationship: str

# 人物提取
class PersonExtract(BaseModel):
    person_id: str
    name: str
    relation: str
    relation_type: RelationType
    first_appear_time: Optional[str] = None
    description: str
    appearance: Optional[str] = None
    personality: Optional[str] = None
    occupation: Optional[str] = None
    key_quotes: List[str] = Field(default_factory=list)
    relationships: List[PersonRelationship] = Field(default_factory=list)
    influence_level: InfluenceLevel = InfluenceLevel.MEDIUM
    source_turns: List[int] = Field(default_factory=list)

# 画像更新
class ProtagonistUpdate(BaseModel):
    birth_year: Optional[str] = None
    birth_place: Optional[str] = None
    key_life_events: List[str] = Field(default_factory=list)
    personality_traits: List[str] = Field(default_factory=list)
    values_hints: List[str] = Field(default_factory=list)

class RelationshipEdge(BaseModel):
    person1_id: str
    person2_id: str
    relationship: str
    evidence: Optional[str] = None

class ProfileUpdates(BaseModel):
    protagonist: Optional[ProtagonistUpdate] = None
    relationship_network: List[RelationshipEdge] = Field(default_factory=list)

# 存储建议
class FileSuggestion(BaseModel):
    event_id: Optional[str] = None
    person_id: Optional[str] = None
    suggested_path: str

class StorageSuggestions(BaseModel):
    timeline_file: Optional[str] = None
    event_files: List[FileSuggestion] = Field(default_factory=list)
    people_files: List[FileSuggestion] = Field(default_factory=list)

# 处理摘要
class ProcessingSummary(BaseModel):
    total_events_extracted: int = 0
    total_people_identified: int = 0
    timeline_nodes_added: int = 0
    confidence_avg: float = 0.0
    notes: Optional[str] = None

# 完整输出
class OrganizedMemory(BaseModel):
    timeline_updates: List[TimelineUpdate] = Field(default_factory=list)
    events: List[EventExtract] = Field(default_factory=list)
    people: List[PersonExtract] = Field(default_factory=list)
    profile_updates: Optional[ProfileUpdates] = None
    storage_suggestions: Optional[StorageSuggestions] = None
    processing_summary: Optional[ProcessingSummary] = None
    
    @classmethod
    def empty(cls) -> "OrganizedMemory":
        return cls()
```

### 5.2 模型文件位置

```
src/models/
├── __init__.py          # 导出所有模型
├── session_state.py
├── conversation_turn.py
├── emotion_result.py
├── memory_query_result.py
├── summary_content.py
├── handoff_package.py
├── event_info.py
├── person_info.py
└── organized_memory.py  # 新增
```

---

## 六、Prompt 模板

### 6.1 模板注册

在 `src/services/llm_service.py` 中注册新模板：

```python
PROMPT_TEMPLATES = {
    # ... 其他模板
    
    "memory_organization": {
        "system_prompt": "...",  # 见 Prompts/MemoryOrganizer-Prompt.md
        "output_format": "json",
        "max_tokens": 3000,  # 整理内容可能较长
        "temperature": 0.3,  # 低温度，保持准确性
    },
}
```

### 6.2 完整 Prompt 文档

详见：`老人自传/Prompts/MemoryOrganizer-Prompt.md`

---

## 七、调用流程图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    MemoryManager 整理存储流程                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ConversationTurns (对话轮次)                                           │
│          │                                                              │
│          ▼                                                              │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │ organize_and_save()                                              │  │
│   │                                                                  │  │
│   │   1. 格式化对话内容                                               │  │
│   │   2. 获取已有时间线/人物索引                                       │  │
│   │   3. 调用 LLMService.invoke_structured()                         │  │
│   │      └── 使用 "memory_organization" 模板                         │  │
│   │      └── 输出 OrganizedMemory                                    │  │
│   │                                                                  │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│          │                                                              │
│          ▼                                                              │
│   OrganizedMemory                                                       │
│   ├── timeline_updates: List[TimelineUpdate]                           │
│   ├── events: List[EventExtract]                                       │
│   ├── people: List[PersonExtract]                                      │
│   └── profile_updates: ProfileUpdates                                  │
│          │                                                              │
│          ▼                                                              │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │ _apply_organized_memory()                                        │  │
│   │                                                                  │  │
│   │   并行保存：                                                      │  │
│   │   ├── events/childhood/xxx.md  (事件文件)                        │  │
│   │   ├── people/family/父亲.md    (人物文件)                        │  │
│   │   └── timeline/childhood.md    (时间线文件)                      │  │
│   │                                                                  │  │
│   │   更新画像：                                                      │  │
│   │   ├── protagonist.birth_year                                    │  │
│   │   ├── protagonist.personality_traits                            │  │
│   │   └── relationship_network                                      │  │
│   │                                                                  │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 八、更新后的验收标准

- [ ] MemoryRepository实现完成
- [ ] MemoryManager实现完成（含 LLM 整理）
- [ ] **新增 OrganizedMemory 及相关数据模型**
- [ ] **Prompt 模板 "memory_organization" 注册完成**
- [ ] LRU缓存正常工作
- [ ] 三层记忆读写正常
- [ ] **LLM 整理流程正常工作**
- [ ] 并行保存正常工作
- [ ] 单元测试覆盖率 > 80%
