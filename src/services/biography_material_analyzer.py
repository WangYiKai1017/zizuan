"""传记材料分析器

负责扫描和解析知识库中的采访材料，为 Agent 的 LLM 节点准备结构化输入。
不做 LLM 调用，只做文件读取和内容解析。
"""

import logging
import re
from pathlib import Path
from typing import Optional

from src.models.biography_models import (
    EventSummary,
    PersonSummary,
    TimelineEntry,
)
from src.services.biography_file_manager import BiographyFileManager

logger = logging.getLogger(__name__)


class BiographyMaterialAnalyzer:
    """传记材料分析器"""

    def __init__(self, file_manager: BiographyFileManager):
        self.file_manager = file_manager

    def scan_and_parse_all(self) -> dict:
        """扫描并解析所有知识库材料

        Returns:
            {
                "events": list[EventSummary],
                "people": list[PersonSummary],
                "timeline": list[TimelineEntry],
                "raw_content": str  # All materials as formatted text for LLM
            }
        """
        logger.info("开始扫描和解析所有知识库材料")

        events = self.parse_events()
        people = self.parse_people()
        timeline = self.parse_timeline()
        raw_content = self.format_materials_for_llm(events, people, timeline)

        logger.info(
            "材料解析完成: %d 个事件, %d 个人物, %d 条时间线",
            len(events),
            len(people),
            len(timeline),
        )

        return {
            "events": events,
            "people": people,
            "timeline": timeline,
            "raw_content": raw_content,
        }

    def parse_events(self) -> list[EventSummary]:
        """解析 events/ 目录下的所有事件文档

        从每个事件 .md 文件中提取:
        - title: 从 # 标题行
        - life_stage: 从文件所在子目录名 (childhood/youth/middle_age/elderly)
        - event_type: 从 基本信息 -> 事件类型
        - description: 从 事件描述 section
        - people: 从 相关人物 section (提取wiki link中的显示名)
        - emotion_tags: 从 情感标签 section (提取 #tag 格式)
        """
        events: list[EventSummary] = []
        kb_files = self.file_manager.scan_kb_files()
        event_files = [f for f in kb_files if f.startswith("events/")]

        logger.info("发现 %d 个事件文件", len(event_files))

        for file_path in event_files:
            try:
                content = self.file_manager.read_kb_file(file_path)
                event = self._parse_single_event(file_path, content)
                events.append(event)
                logger.debug("已解析事件: %s", event.title)
            except Exception as e:
                logger.warning("解析事件文件失败 %s: %s", file_path, e)
                continue

        return events

    def parse_people(self) -> list[PersonSummary]:
        """解析 people/ 目录下的所有人物文档

        从每个人物 .md 文件中提取:
        - name: 从 # 标题行
        - relationship: 从 基本信息 -> 关系
        - description: 从 基本信息 -> 描述
        - influence: 从 对主人公的影响
        - quotes: 从 重要语录 section (提取 > 引用行)
        """
        people: list[PersonSummary] = []
        kb_files = self.file_manager.scan_kb_files()
        people_files = [f for f in kb_files if f.startswith("people/")]

        logger.info("发现 %d 个人物文件", len(people_files))

        for file_path in people_files:
            try:
                content = self.file_manager.read_kb_file(file_path)
                person = self._parse_single_person(file_path, content)
                people.append(person)
                logger.debug("已解析人物: %s", person.name)
            except Exception as e:
                logger.warning("解析人物文件失败 %s: %s", file_path, e)
                continue

        return people

    def parse_timeline(self) -> list[TimelineEntry]:
        """解析 timeline/ 目录下的时间线文档

        从 life-events.md 中提取各阶段的事件条目:
        - life_stage: 从 ## 标题中提取
        - event_title: 从 事件 字段
        - event_type: 从 类型 字段
        - detail_link: 从 详情 字段中的 wiki link
        """
        entries: list[TimelineEntry] = []
        timeline_path = "timeline/life-events.md"

        try:
            content = self.file_manager.read_kb_file(timeline_path)
        except Exception as e:
            logger.warning("读取时间线文件失败: %s", e)
            return entries

        # 按 ## 标题分段
        sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)

        for section in sections:
            section = section.strip()
            if not section.startswith("## "):
                continue

            # 提取阶段标题
            header_match = re.match(r"^## (.+)$", section, re.MULTILINE)
            if not header_match:
                continue
            life_stage = header_match.group(1).strip()

            # 提取事件条目
            event_match = re.search(
                r"\*\*事件\*\*[:：]\s*(.+)", section
            )
            type_match = re.search(
                r"\*\*类型\*\*[:：]\s*(.+)", section
            )
            detail_match = re.search(
                r"\*\*详情\*\*[:：]\s*(.+)", section
            )

            event_title = event_match.group(1).strip() if event_match else ""
            event_type = type_match.group(1).strip() if type_match else ""
            detail_link = ""
            if detail_match:
                link_names = self._extract_wiki_link_names(
                    detail_match.group(1)
                )
                detail_link = detail_match.group(1).strip()

            entry = TimelineEntry(
                life_stage=life_stage,
                event_title=event_title,
                event_type=event_type,
                detail_link=detail_link,
            )
            entries.append(entry)
            logger.debug("已解析时间线条目: %s - %s", life_stage, event_title)

        logger.info("解析时间线完成: %d 条条目", len(entries))
        return entries

    def format_materials_for_llm(
        self,
        events: list[EventSummary],
        people: list[PersonSummary],
        timeline: list[TimelineEntry],
    ) -> str:
        """将解析后的材料格式化为LLM可读的文本

        输出格式为分类整理的纯文本，便于LLM理解和引用。
        """
        lines: list[str] = []

        # === 事件材料 ===
        lines.append("=== 事件材料 ===\n")

        # 按 life_stage 分组
        stage_events: dict[str, list[EventSummary]] = {}
        for event in events:
            stage = event.life_stage or "未分类"
            if stage not in stage_events:
                stage_events[stage] = []
            stage_events[stage].append(event)

        stage_display = {
            "childhood": "童年时期",
            "youth": "青年时期",
            "middle_age": "中年时期",
            "elderly": "老年时期",
            "未分类": "未分类",
        }

        for stage, stage_event_list in stage_events.items():
            display_name = stage_display.get(stage, stage)
            lines.append(f"【{display_name}】")
            for i, event in enumerate(stage_event_list, 1):
                lines.append(f"{i}. {event.title}")
                if event.description:
                    lines.append(f"   - 描述：{event.description}")
                if event.people:
                    lines.append(
                        f"   - 相关人物：{'、'.join(event.people)}"
                    )
                if event.emotion_tags:
                    lines.append(
                        f"   - 情感：{'、'.join(event.emotion_tags)}"
                    )
                lines.append("")
            lines.append("")

        # === 人物档案 ===
        lines.append("=== 人物档案 ===\n")

        for i, person in enumerate(people, 1):
            relationship_info = (
                f"（{person.relationship}）" if person.relationship else ""
            )
            lines.append(f"{i}. {person.name}{relationship_info}")
            if person.description:
                lines.append(f"   - 描述：{person.description}")
            if person.influence:
                lines.append(f"   - 影响程度：{person.influence}")
            if person.quotes:
                for quote in person.quotes:
                    lines.append(f'   - 语录："{quote}"')
            lines.append("")

        # === 时间线 ===
        lines.append("=== 时间线 ===\n")

        # 按 life_stage 分组
        stage_entries: dict[str, list[TimelineEntry]] = {}
        for entry in timeline:
            stage = entry.life_stage or "未分类"
            if stage not in stage_entries:
                stage_entries[stage] = []
            stage_entries[stage].append(entry)

        for stage, entry_list in stage_entries.items():
            lines.append(f"【{stage}】")
            for entry in entry_list:
                type_info = f" ({entry.event_type})" if entry.event_type else ""
                lines.append(f"- {entry.event_title}{type_info}")
            lines.append("")

        return "\n".join(lines)

    def gather_chapter_materials(
        self, source_materials: list[str], life_stage: str
    ) -> dict:
        """为特定章节收集写作所需的全部材料

        Args:
            source_materials: 章节引用的知识库文件路径列表
            life_stage: 章节所属人生阶段

        Returns:
            {
                "source_content": str,       # 源文件完整内容
                "character_profiles": str,   # 相关人物信息
                "timeline_context": str      # 时间线上下文
            }
        """
        logger.info(
            "收集章节材料: %d 个源文件, 阶段=%s",
            len(source_materials),
            life_stage,
        )

        # 1. 读取所有源材料文件
        source_content_parts: list[str] = []
        referenced_people: set[str] = set()

        for material_path in source_materials:
            try:
                content = self.file_manager.read_kb_file(material_path)
                source_content_parts.append(
                    f"--- {material_path} ---\n{content}"
                )
                # 从源文件中提取引用的人物名
                people_names = self._extract_wiki_link_names(content)
                referenced_people.update(people_names)
            except Exception as e:
                logger.warning("读取源材料失败 %s: %s", material_path, e)
                continue

        source_content = "\n\n".join(source_content_parts)

        # 2. 获取相关人物的档案信息
        character_profiles = self._gather_character_profiles(
            referenced_people
        )

        # 3. 获取时间线上下文
        timeline_context = self._gather_timeline_context(life_stage)

        logger.info(
            "章节材料收集完成: 源内容长度=%d, 人物数=%d",
            len(source_content),
            len(referenced_people),
        )

        return {
            "source_content": source_content,
            "character_profiles": character_profiles,
            "timeline_context": timeline_context,
        }

    def _parse_single_event(
        self, file_path: str, content: str
    ) -> EventSummary:
        """解析单个事件文件"""
        # 提取标题
        title = self._extract_title(content)

        # 确定人生阶段
        life_stage = self._determine_life_stage(file_path)

        # 提取事件类型 (从 基本信息 section)
        basic_info = self._extract_section(content, "基本信息")
        event_type = ""
        if basic_info:
            type_match = re.search(
                r"\*\*事件类型\*\*[:：]\s*(.+)", basic_info
            )
            if type_match:
                # 去除来源标注
                event_type = re.sub(
                    r"（来源：.*?）", "", type_match.group(1)
                ).strip()

        # 提取事件描述
        description = self._extract_section(content, "事件描述")
        if description:
            # 清理来源标注
            description = re.sub(
                r"（来源：.*?）", "", description
            ).strip()

        # 提取相关人物
        people_section = self._extract_section(content, "相关人物")
        people = self._extract_wiki_link_names(people_section) if people_section else []

        # 提取情感标签
        emotion_section = self._extract_section(content, "情感标签")
        emotion_tags = (
            self._extract_emotion_tags(emotion_section)
            if emotion_section
            else []
        )

        return EventSummary(
            file_path=file_path,
            title=title,
            life_stage=life_stage,
            event_type=event_type,
            description=description,
            people=people,
            emotion_tags=emotion_tags,
        )

    def _parse_single_person(
        self, file_path: str, content: str
    ) -> PersonSummary:
        """解析单个人物文件"""
        # 提取姓名
        name = self._extract_title(content)

        # 提取基本信息
        basic_info = self._extract_section(content, "基本信息")
        relationship = ""
        description = ""
        if basic_info:
            rel_match = re.search(
                r"\*\*关系\*\*[:：]\s*(.+)", basic_info
            )
            if rel_match:
                relationship = rel_match.group(1).strip()

            desc_match = re.search(
                r"\*\*描述\*\*[:：]\s*(.+)", basic_info
            )
            if desc_match:
                description = desc_match.group(1).strip()

        # 提取影响程度
        influence_section = self._extract_section(content, "对主人公的影响")
        influence = influence_section.strip() if influence_section else ""

        # 提取重要语录 (> 引用行)
        quotes_section = self._extract_section(content, "重要语录")
        quotes: list[str] = []
        if quotes_section:
            for line in quotes_section.split("\n"):
                line = line.strip()
                if line.startswith(">"):
                    quote_text = line.lstrip(">").strip()
                    if quote_text and quote_text != "暂无":
                        quotes.append(quote_text)

        return PersonSummary(
            file_path=file_path,
            name=name,
            relationship=relationship,
            description=description,
            influence=influence,
            quotes=quotes,
        )

    def _extract_title(self, content: str) -> str:
        """从 markdown 内容中提取 # 标题"""
        match = re.match(r"^#\s+(.+)$", content.strip(), re.MULTILINE)
        return match.group(1).strip() if match else ""

    def _extract_section(self, content: str, section_name: str) -> str:
        """从 markdown 内容中提取指定 section 的内容

        支持 ## 和 ### 级别的 section 标题。

        Args:
            content: 完整的 markdown 文本
            section_name: section 标题（如 "事件描述", "基本信息"）

        Returns:
            该 section 下的内容文本
        """
        # 尝试匹配 ## 或 ### 级别的 section
        pattern = re.compile(
            r"^(#{2,3})\s+" + re.escape(section_name) + r"\s*\n"
            r"(.*?)"
            r"(?=^#{2,3}\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(content)
        if match:
            return match.group(2).strip()
        return ""

    def _extract_wiki_link_names(self, text: str) -> list[str]:
        """从文本中提取所有 wiki link 的显示名称

        Wiki link 格式: [[path|display_name]] 或 [[path]]
        """
        if not text:
            return []

        names: list[str] = []

        # 匹配 [[path|display_name]] 格式
        pattern_with_name = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
        for match in pattern_with_name.finditer(text):
            display_name = match.group(2).strip()
            names.append(display_name)

        # 匹配 [[path]] 格式（无显示名称，使用文件名）
        pattern_no_name = re.compile(r"\[\[([^\]|]+)\]\]")
        for match in pattern_no_name.finditer(text):
            path = match.group(1).strip()
            # 使用文件名（去除扩展名）作为显示名
            filename = Path(path).stem
            if filename not in names:
                names.append(filename)

        return names

    def _extract_emotion_tags(self, text: str) -> list[str]:
        """从文本中提取 #tag 格式的情感标签"""
        if not text:
            return []

        # 匹配 #tag 格式，支持中文和英文标签
        # 排除 markdown 标题行 (## / ###)
        tags: list[str] = []
        pattern = re.compile(r"(?<![#])#([\w\u4e00-\u9fff]+)")
        for match in pattern.finditer(text):
            tag = match.group(1).strip()
            # 去除来源标注中可能混入的内容
            if "来源" not in tag and tag not in tags:
                tags.append(tag)

        return tags

    def _determine_life_stage(self, file_path: str) -> str:
        """从文件路径中确定人生阶段

        路径格式: events/childhood/xxx.md -> "childhood"
        """
        parts = Path(file_path).parts
        # 预期结构: events/<life_stage>/filename.md
        if len(parts) >= 2:
            # parts[0] = "events", parts[1] = life_stage
            stage = parts[1]
            valid_stages = {"childhood", "youth", "middle_age", "elderly"}
            if stage in valid_stages:
                return stage

        logger.debug("无法从路径确定人生阶段: %s", file_path)
        return ""

    def _gather_character_profiles(
        self, people_names: set[str]
    ) -> str:
        """收集指定人物的档案信息"""
        if not people_names:
            return ""

        all_people = self.parse_people()
        profiles: list[str] = []

        for person in all_people:
            if person.name in people_names:
                profile_lines = [f"【{person.name}】"]
                if person.relationship:
                    profile_lines.append(f"- 关系：{person.relationship}")
                if person.description:
                    profile_lines.append(f"- 描述：{person.description}")
                if person.influence:
                    profile_lines.append(f"- 影响：{person.influence}")
                if person.quotes:
                    for quote in person.quotes:
                        profile_lines.append(f'- 语录："{quote}"')
                profiles.append("\n".join(profile_lines))

        return "\n\n".join(profiles)

    def _gather_timeline_context(self, life_stage: str) -> str:
        """收集特定人生阶段的时间线上下文"""
        # 英文阶段名到中文关键字的映射
        stage_keywords = {
            "childhood": "童年",
            "youth": "青年",
            "middle_age": "中年",
            "elderly": "老年",
        }

        all_timeline = self.parse_timeline()
        keyword = stage_keywords.get(life_stage, life_stage)

        relevant_entries = [
            entry
            for entry in all_timeline
            if keyword in entry.life_stage
            or life_stage in entry.life_stage.lower()
            or life_stage == entry.life_stage
        ]

        if not relevant_entries:
            return ""

        lines: list[str] = []
        for entry in relevant_entries:
            type_info = f" ({entry.event_type})" if entry.event_type else ""
            lines.append(f"- {entry.event_title}{type_info}")

        return "\n".join(lines)
