from typing import Dict, List, Any, Optional
from collections import OrderedDict
from datetime import datetime
import json
import logging
import os

from src.storage.markdown_file_manager import MarkdownFileManager
from src.services.knowledge_base_querier import KnowledgeBaseQuerier
from src.services.llm_service import get_llm_service
from src.models import EventInfo, PersonInfo, SessionState

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
        
        # 知识库查询者
        self.llm_service = get_llm_service()
        self.knowledge_base_querier = KnowledgeBaseQuerier(
            file_manager=self.file_manager,
            llm_service=self.llm_service
        )
    
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
    
    async def get_latest_conversation_records(self, user_id: str, n: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        从知识库中获取最新的对话记录
        
        Args:
            user_id: 用户ID
            n: 返回最近的n条记录（如果为None，则返回所有记录）
            
        Returns:
            对话历史记录列表
        """
        try:
            # 列出用户知识库目录下的所有JSON文件
            files = self.file_manager.list_files(include_details=True, recursive=True)
            conversation_files = []
            
            for file in files:
                if file["is_file"] and file["name"].startswith("conversation_") and file["name"].endswith(".json"):
                    conversation_files.append(file)
            
            if not conversation_files:
                return []
            
            # 从文件名中提取时间戳进行排序，文件名格式为 conversation_YYYY-MM-DD_HH-MM-SS.json
            def extract_timestamp(file):
                file_name = file["name"]
                # 提取 YYYY-MM-DD_HH-MM-SS 部分
                timestamp_str = file_name.replace("conversation_", "").replace(".json", "")
                try:
                    # 转换为 datetime 对象
                    return datetime.strptime(timestamp_str, "%Y-%m-%d_%H-%M-%S")
                except ValueError:
                    # 如果文件名格式不正确，使用文件的修改时间
                    return datetime.fromisoformat(file["modified"])
            
            # 按时间戳排序，找到最新的对话记录文件
            conversation_files.sort(key=extract_timestamp, reverse=True)
            latest_file = conversation_files[0]
            
            # 读取最新的对话记录文件
            file_content = self.file_manager.read_file_sync(latest_file["path"])
            conversation_history = json.loads(file_content)
            
            # 如果指定了n，返回最近的n条记录
            if n:
                return conversation_history[-n:]
            
            return conversation_history
        except Exception as e:
            logger.error(f"Failed to get latest conversation records: {e}")
            return []
    
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
        duplicate_path = self._remove_duplicate_event_files(event, relative_path)
        if duplicate_path:
            relative_path = duplicate_path
        
        # 转换为Markdown并保存
        content = event.to_markdown()
        path = await self.file_manager.create_file(relative_path, content, overwrite=True)
        
        # 更新索引
        self._event_index[event.event_id] = event
        self._cache.put(f"event:{event.event_id}", event)
        
        logger.info(f"Saved event: {event.event_id} to {path}")
        return path
    
    async def save_person(self, person: PersonInfo) -> str:
        """保存人物信息"""
        if not person.person_id:
            raise ValueError("Person must have an ID")
        
        # 确定存储路径
        if (
            person.role.lower() == "protagonist"
            or person.relation_to_protagonist in ["自己", "本人", "主人公", "被采访者"]
            or person.role in ["自己", "本人", "主人公", "被采访者"]
            or person.name == "主人公"
        ):
            # 主人公信息单独存储
            relative_path = "people/protagonist.md"
        else:
            # 其他人物按角色存储
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
        file_path = self.file_manager.base_path / timeline_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(self._build_timeline_from_event_files(), encoding="utf-8")

    def _build_timeline_from_event_files(self) -> str:
        """根据当前事件文件重建时间线，避免追加式写入留下重复或失效链接。"""
        events_root = self.file_manager.base_path / "events"
        entries = []
        seen = set()

        for md_file in sorted(events_root.rglob("*.md")) if events_root.exists() else []:
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            title = self._extract_markdown_title(content)
            time_text = self._extract_markdown_field(content, "时间")
            event_type = self._extract_markdown_field(content, "事件类型")
            if not title or not time_text:
                continue

            key = (self._extract_year(time_text) or time_text, title)
            if key in seen:
                continue
            seen.add(key)

            rel = md_file.relative_to(self.file_manager.base_path).as_posix()
            entries.append({
                "year": self._extract_year(time_text) or time_text,
                "time": time_text,
                "title": title,
                "type": event_type or "other",
                "path": rel,
            })

        entries.sort(key=lambda item: (item["year"], item["title"]))
        lines = []
        for item in entries:
            lines.extend([
                f"## {item['time']}",
                f"- **事件**: {item['title']}",
                f"- **类型**: {item['type']}",
                f"- **详情**: [[../{item['path']}|查看详情]]",
                "",
            ])
        return "\n".join(lines).rstrip() + ("\n" if lines else "")
    
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
        self._short_term[f"profile:{key}"] = {
            "value": value,
            "timestamp": datetime.now().isoformat(),
        }
    
    def get_profile(self, key: str) -> Optional[Any]:
        """获取画像记忆"""
        entry = self._short_term.get(f"profile:{key}")
        return entry["value"] if entry else None
    
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
        
        # 提取年份（如果有）
        import re
        year_match = re.search(r'\d{4}', time_lower)
        if year_match:
            year = int(year_match.group(0)[:4])
            if year <= 1960:  # 简化：出生及早年
                return "childhood"
            elif year >= 1961 and year <= 1970:  # 少年
                return "youth"
            elif year >= 1971 and year <= 2010:  # 青壮年/中年
                return "middle_age"
        
        # 根据关键词判断
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
        if role in ["父亲", "母亲", "配偶", "子女", "妻子", "丈夫", "老伴", "女儿", "儿子", "外孙女", "外孙", "孙女", "孙子"]:
            return "family"
        elif role in ["朋友", "邻居"]:
            return "friends"
        elif role in ["同事", "上司", "下属", "徒弟", "师傅"]:
            return "colleagues"
        else:
            return "others"
    
    def _generate_event_filename(self, title: str) -> str:
        """生成事件文件名"""
        # 简化：使用标题的拼音或英文
        import re
        name = re.sub(r'[^\w\u4e00-\u9fff]', '-', title)
        return name[:50]  # 限制长度

    def _remove_duplicate_event_files(self, event: EventInfo, target_relative_path: str) -> Optional[str]:
        """删除同一年份、同类型、标题高度相似的旧事件文件。"""
        phase_dir = self._get_phase_directory(event.time)
        dir_path = self.file_manager.base_path / "events" / phase_dir
        if not dir_path.exists():
            return None

        target_path = self.file_manager.base_path / target_relative_path
        event_year = self._extract_year(event.time)
        for md_file in dir_path.glob("*.md"):
            if md_file == target_path:
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            existing_title = self._extract_markdown_title(content)
            existing_time = self._extract_markdown_field(content, "时间")
            existing_type = self._extract_markdown_field(content, "事件类型")

            if event.type == "birth" and existing_type == "birth":
                should_remove = True
            else:
                should_remove = False

            if not should_remove and event_year and self._extract_year(existing_time) != event_year:
                continue
            if existing_type and event.type and existing_type != event.type:
                continue
            if not should_remove and not self._titles_refer_to_same_event(
                existing_title,
                event.title,
                event.type,
            ):
                continue

            if len(existing_title) >= len(event.title or ""):
                event.title = existing_title
                return md_file.relative_to(self.file_manager.base_path).as_posix()

            try:
                md_file.unlink()
                logger.info(f"Removed duplicate event file: {md_file}")
            except Exception as e:
                logger.warning(f"Failed to remove duplicate event file {md_file}: {e}")
        return None

    def _extract_year(self, value: str) -> str:
        import re
        match = re.search(r"\d{4}", value or "")
        return match.group(0) if match else ""

    def _extract_markdown_title(self, content: str) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return ""

    def _extract_markdown_field(self, content: str, label: str) -> str:
        import re
        pattern = rf"- \*\*{re.escape(label)}\*\*：(.+)"
        match = re.search(pattern, content)
        return match.group(1).strip() if match else ""

    def _title_similarity(self, left: str, right: str) -> float:
        left_chars = {ch for ch in left or "" if ch.strip()}
        right_chars = {ch for ch in right or "" if ch.strip()}
        if not left_chars or not right_chars:
            return 0.0
        return len(left_chars & right_chars) / len(left_chars | right_chars)

    def _titles_refer_to_same_event(self, left: str, right: str, event_type: str) -> bool:
        if self._title_similarity(left, right) >= 0.25:
            return True
        if event_type == "career":
            career_tokens = ["学徒", "进厂", "机械厂", "铁路机械厂", "南京铁路机械厂"]
            if "学徒" in (left or "") and "学徒" in (right or ""):
                if any(token in (left or "") or token in (right or "") for token in career_tokens[1:]):
                    return True
        return False
    
    def _sanitize_filename(self, name: str) -> str:
        """清理文件名"""
        import re
        return re.sub(r'[^\w\u4e00-\u9fff]', '-', name)[:50]
