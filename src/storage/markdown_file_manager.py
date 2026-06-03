import os
import re
import aiofiles
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)


class LinkedContent(BaseModel):
    """链接内容"""
    source: str                     # 源文件路径
    target: str                     # 目标文件路径
    display_name: str               # 显示名称
    anchor: Optional[str] = None    # 锚点
    content_preview: str = ""       # 内容预览


class SearchResult(BaseModel):
    """搜索结果"""
    file_path: str
    line_number: int
    matched_text: str
    context: str                    # 上下文
    relevance: float = 0.0


class MarkdownFileManager:
    """
    Markdown文件管理器
    
    职责：
    - 管理记忆库的md文件
    - 创建、读取、更新文件
    - 全文搜索
    - Wiki链接追踪
    
    使用场景：
    - KnowledgeBaseQuerier 查询记忆
    - ContentSummarizer 写入记忆
    - MemoryRepository 存储层实现
    """
    
    def __init__(self, base_path: str = None, conversation_id: str = None):
        """
        初始化
        
        Args:
            base_path: 记忆库根目录
            conversation_id: 对话ID，如果不提供则自动生成
        """
        # 如果未指定路径，使用用户的临时目录
        if base_path is None:
            temp_path = Path(os.environ.get("TEMP", "/tmp")) / "memory"
            base_path = str(temp_path)
        
        # 生成或使用提供的对话ID
        if conversation_id:
            # 使用提供的对话ID
            self.conversation_id = conversation_id
            # 完整的存储路径：memory/{conversation_id}
            self.base_path = Path(base_path) / self.conversation_id
            logger.info(f"Initializing MarkdownFileManager for conversation {self.conversation_id} at {self.base_path}")
            self._ensure_directory_structure()
        else:
            # 未提供对话ID，直接使用base_path
            self.base_path = Path(base_path)
            logger.info(f"Using base path directly: {self.base_path}")
            self._ensure_directory_structure()

        print("*" * 30)
        print("初始化部分")
        print(self.base_path)
        print("*" * 30)
        
    
    def _ensure_directory_structure(self) -> None:
        """确保目录结构存在"""
        directories = [
            "events/childhood",
            "events/youth",
            "events/middle_age",
            "events/elderly",
            "people/family",
            "people/friends",
            "people/colleagues",
            "people/others",
            "timeline",
            "themes",
        ]
        
        for dir_path in directories:
            full_path = self.base_path / dir_path
            full_path.mkdir(parents=True, exist_ok=True)
        
        # 创建索引文件
        index_path = self.base_path / "index.md"
        if not index_path.exists():
            self._create_index_file()
    
    def _create_index_file(self) -> None:
        """创建索引文件"""
        sections = [
            "# 记忆库索引",
            "",
            "## 事件",
            f"- {self.format_wiki_link('童年事件', 'events/childhood/')}",
            f"- {self.format_wiki_link('少年事件', 'events/youth/')}",
            f"- {self.format_wiki_link('中年事件', 'events/middle_age/')}",
            f"- {self.format_wiki_link('老年事件', 'events/elderly/')}",
            "",
            "## 人物",
            f"- {self.format_wiki_link('主人公', 'people/protagonist.md')}",
            f"- {self.format_wiki_link('家庭成员', 'people/family/')}",
            f"- {self.format_wiki_link('朋友', 'people/friends/')}",
            f"- {self.format_wiki_link('同事', 'people/colleagues/')}",
            f"- {self.format_wiki_link('其他', 'people/others/')}",
            "",
            "## 时间线",
            f"- {self.format_wiki_link('人生大事年表', 'timeline/life-events.md')}",
            "",
            "## 主题",
            f"- {self.format_wiki_link('价值观形成', 'themes/values.md')}",
            f"- {self.format_wiki_link('人生转折点', 'themes/turning-points.md')}",
            "",
        ]
        content = "\n".join(sections)
        index_path = self.base_path / "index.md"
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(content)

    # ========== user.md and summary_index ==========

    def create_or_update_user_md(self, profile_info: dict) -> str:
        """创建或更新被采访者档案文件 user.md

        Args:
            profile_info: 包含被采访者信息的字典，键如:
                wechat_id, name, age, gender, birth_date,
                birth_year, occupation, family_status,
                living_arrangement, story_expectation,
                supplementary (补充信息字符串)

        Returns:
            写入文件的绝对路径
        """
        user_md_path = self.base_path / "user.md"

        field_labels = {
            "wechat_id": "微信ID",
            "name": "姓名",
            "age": "年龄",
            "gender": "性别",
            "birth_date": "出生日期",
            "birth_year": "出生年份",
            "occupation": "职业",
            "family_status": "家庭状况",
            "living_arrangement": "居住情况",
            "story_expectation": "故事期望",
        }

        if not user_md_path.exists():
            # --- Create new file ---
            lines = ["# 被采访者档案", "", "## 基本信息"]
            for key, label in field_labels.items():
                value = profile_info.get(key)
                if value:
                    lines.append(f"- {label}: {value}")
            lines.append("")
            lines.append("## 补充信息")
            supplementary = profile_info.get("supplementary")
            if supplementary:
                lines.append(f"\n{supplementary}")
            lines.append("")
            content = "\n".join(lines)
            with open(user_md_path, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            # --- Update existing file ---
            with open(user_md_path, "r", encoding="utf-8") as f:
                existing = f.read()

            # Update 基本信息 section
            for key, label in field_labels.items():
                value = profile_info.get(key)
                if not value:
                    continue
                pattern = rf"(- {re.escape(label)}: )(.*)"  
                if re.search(pattern, existing):
                    existing = re.sub(pattern, rf"\g<1>{value}", existing)
                else:
                    # Insert before 补充信息 section
                    marker = "## 补充信息"
                    if marker in existing:
                        existing = existing.replace(
                            marker, f"- {label}: {value}\n\n{marker}"
                        )
                    else:
                        existing += f"\n- {label}: {value}\n"

            # Append supplementary info if provided
            supplementary = profile_info.get("supplementary")
            if supplementary:
                marker = "## 补充信息"
                supplementary = str(supplementary).strip()
                if not supplementary or supplementary in existing:
                    pass
                elif marker in existing:
                    existing = existing.rstrip("\n") + f"\n\n{supplementary}\n"
                else:
                    existing += f"\n## 补充信息\n\n{supplementary}\n"

            with open(user_md_path, "w", encoding="utf-8") as f:
                f.write(existing)

        logger.info(f"Created/updated user.md at {user_md_path}")
        return str(user_md_path)

    def create_or_update_summary_index(self) -> str:
        """扫描用户知识库目录，生成 summary_index.md 摘要目录。

        - 使用 format_wiki_link() 生成所有链接
        - 跳过包含 'biography' 的路径
        - 空目录的分类不写入
        - 文件按字母排序

        Returns:
            写入文件的绝对路径
        """
        summary_path = self.base_path / "summary_index.md"

        # Section definitions: (heading, subdirs list relative to base_path)
        sections = [
            ("事件记录", ["events/childhood", "events/youth", "events/middle_age", "events/elderly"]),
            ("人物关系", ["people/family", "people/friends", "people/colleagues", "people/others"]),
            ("时间线", ["timeline"]),
            ("主题", ["themes"]),
            ("采访记录", ["sessions"]),
        ]

        def _get_brief(file_path: Path) -> str:
            """Read the first meaningful line (title) or first 50 chars."""
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    first_line = f.readline().strip()
                # Strip leading '#' for title lines
                brief = first_line.lstrip("# ").strip()
                if not brief:
                    # Try reading more
                    with open(file_path, "r", encoding="utf-8") as f:
                        brief = f.read(50).replace("\n", " ").strip()
                return brief[:50]
            except Exception:
                return ""

        output_lines = ["# 记忆库摘要目录", ""]

        # User profile section
        user_md_path = self.base_path / "user.md"
        if user_md_path.exists():
            output_lines.append("## 被采访者档案")
            link = self.format_wiki_link("被采访者档案", "user.md")
            output_lines.append(f"- {link} — 被采访者基本信息和个人档案")
            output_lines.append("")

        # Content sections
        for heading, subdirs in sections:
            entries = []
            for subdir in subdirs:
                dir_path = self.base_path / subdir
                if not dir_path.exists():
                    continue
                for md_file in sorted(dir_path.rglob("*.md")):
                    # Skip biography paths
                    rel = str(md_file.relative_to(self.base_path)).replace(os.sep, "/")
                    if "biography" in rel.lower():
                        continue
                    display = md_file.stem
                    brief = _get_brief(md_file)
                    link = self.format_wiki_link(display, rel)
                    entries.append(f"- {link} — {brief}")

            if entries:
                output_lines.append(f"## {heading}")
                output_lines.extend(entries)
                output_lines.append("")

        content = "\n".join(output_lines)
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Generated summary_index.md at {summary_path}")
        return str(summary_path)

    # ========== Wiki link formatting ==========

    def _normalize_wiki_link(self, target_path: str) -> str:
        """Normalize a file path to be relative from the user's KB root.

        Given any path (absolute or relative), strips everything up to and
        including the user's KB directory to produce a clean relative path.

        Examples:
            '/project/knowledge_base/user001/events/childhood/play.md'
              -> 'events/childhood/play.md'
            'knowledge_base/user001/people/family/mom.md'
              -> 'people/family/mom.md'
            'events/childhood/play.md'  -> 'events/childhood/play.md'

        Edge cases:
            - None or empty string -> returns ''
            - Paths containing '..' segments are normalized via posix rules
            - Backslashes are converted to forward slashes
            - Trailing slash is preserved only for directory-style links
              (those that originally ended with '/')
        """
        if not target_path:
            return ""

        # Normalize separators to forward slashes
        path = str(target_path).replace("\\", "/").strip()
        if not path:
            return ""

        had_trailing_slash = path.endswith("/")

        # Resolve '..' and '.' segments using posix-style normalization while
        # preserving an absolute prefix if present.
        is_abs = path.startswith("/")
        normalized = os.path.normpath(path).replace(os.path.sep, "/")
        if is_abs and not normalized.startswith("/"):
            normalized = "/" + normalized

        # Try to strip the user's KB directory prefix.
        # Build a marker like 'knowledge_base/<conversation_id>/' when we know it.
        user_marker = None
        if getattr(self, "conversation_id", None):
            user_marker = f"knowledge_base/{self.conversation_id}/"

        stripped = normalized

        if user_marker and user_marker in stripped:
            stripped = stripped.split(user_marker, 1)[1]
        else:
            # Generic fallback: locate any 'knowledge_base/<segment>/' prefix
            kb_token = "knowledge_base/"
            idx = stripped.find(kb_token)
            if idx != -1:
                tail = stripped[idx + len(kb_token):]
                # Drop the user-id segment that follows knowledge_base/
                if "/" in tail:
                    stripped = tail.split("/", 1)[1]
                else:
                    stripped = tail
            elif stripped.startswith("/"):
                # Absolute path without a knowledge_base anchor: try to make it
                # relative to base_path if possible, otherwise keep as-is
                # (without the leading slash) so it doesn't escape the KB root.
                try:
                    base = str(self.base_path).replace(os.path.sep, "/").rstrip("/") + "/"
                    if stripped.startswith(base):
                        stripped = stripped[len(base):]
                    else:
                        stripped = stripped.lstrip("/")
                except Exception:
                    stripped = stripped.lstrip("/")

        # Collapse any accidental double slashes
        while "//" in stripped:
            stripped = stripped.replace("//", "/")

        # Drop a leading './' if it appears
        if stripped.startswith("./"):
            stripped = stripped[2:]

        # Preserve directory trailing slash if originally present
        if had_trailing_slash and not stripped.endswith("/"):
            stripped = stripped + "/"
        elif not had_trailing_slash:
            stripped = stripped.rstrip("/") if stripped.endswith("/") and "/" in stripped[:-1] else stripped

        return stripped

    def format_wiki_link(self, display_text: str, target_path: str) -> str:
        """Create a properly formatted markdown link with a normalized path.

        The resulting path is always relative to the user's KB root
        (knowledge_base/{user_id}/), regardless of whether ``target_path``
        was supplied as an absolute path, a path containing the KB prefix,
        or an already-relative path.
        """
        rel_path = self._normalize_wiki_link(target_path)
        text = display_text if display_text is not None else ""
        return f"[{text}]({rel_path})"
    
    # ========== 文件操作 ==========
    
    async def create_file(
        self,
        relative_path: str,
        content: str,
        overwrite: bool = False
    ) -> str:
        """
        创建md文件
        
        Args:
            relative_path: 相对路径（相对于base_path）
            content: 文件内容
            overwrite: 是否覆盖已存在的文件
            
        Returns:
            创建的文件路径
        """
        file_path = self.base_path / relative_path
        
        if file_path.exists():
            if not overwrite:
                logger.warning(f"File already exists: {file_path}, use append mode instead of overwrite")
                # 如果文件已存在且不允许覆盖，使用追加模式
                return await self.update_file(relative_path, content, append=True)
            else:
                logger.warning(f"Overwriting existing file: {file_path}")
        
        # 确保父目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
            await f.write(content)
        
        logger.info(f"Created file: {file_path}")
        return str(file_path)
    
    async def read_file(self, path: str) -> str:
        """
        读取md文件（异步版本）
        
        Args:
            path: 可以是相对路径（相对于base_path）或绝对路径
            
        Returns:
            文件内容
        """
        # 检查是否为绝对路径

        if os.path.isabs(path):
            file_path = Path(path)
        else:
            file_path = self.base_path / path
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        print("*" * 30)
        print("读取文件async")
        print(file_path)
        print("*" * 30)

        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
            content = await f.read()
        
        return content
    
    def read_file_sync(self, path: str) -> str:
        """
        读取md文件（同步版本）
        
        Args:
            path: 可以是相对路径（相对于base_path）或绝对路径
            
        Returns:
            文件内容
        """

        # 检查是否为绝对路径
        if os.path.isabs(path):
            file_path = Path(path)
        else:
            file_path = self.base_path / path
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        print("*" * 30)
        print("读取文件sync")
        print(file_path)
        print("*" * 30)

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return content
    
    async def update_file(
        self,
        relative_path: str,
        content: str,
        append: bool = False
    ) -> str:
        """
        更新md文件
        
        Args:
            relative_path: 相对路径
            content: 新内容
            append: 是否追加
            
        Returns:
            更新的文件路径
        """
        file_path = self.base_path / relative_path
        
        if not file_path.exists():
            return await self.create_file(relative_path, content)
        
        if append:
            existing = await self.read_file(relative_path)
            content = existing + "\n" + content
        
        async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
            await f.write(content)
        
        logger.info(f"Updated file: {file_path}")
        return str(file_path)
    
    async def append_section(
        self,
        relative_path: str,
        section_title: str,
        section_content: str
    ) -> str:
        """
        追加章节到文件
        
        Args:
            relative_path: 相对路径
            section_title: 章节标题
            section_content: 章节内容
            
        Returns:
            更新的文件路径
        """
        content = f"\n## {section_title}\n\n{section_content}\n"
        return await self.update_file(relative_path, content, append=True)
    
    # ========== 搜索功能 ==========
    
    async def search_files(
        self,
        keyword: str,
        directory: Optional[str] = None,
        max_results: int = 20
    ) -> List[SearchResult]:
        """
        全文搜索
        
        Args:
            keyword: 搜索关键词
            directory: 限定目录（可选）
            max_results: 最大结果数
            
        Returns:
            搜索结果列表
        """
        results = []
        search_path = self.base_path / directory if directory else self.base_path
        
        # 遍历所有md文件
        for md_file in search_path.rglob("*.md"):
            try:
                content = await self.read_file(str(md_file.relative_to(self.base_path)))
                lines = content.split('\n')
                
                for i, line in enumerate(lines):
                    if keyword.lower() in line.lower():
                        # 计算相关度
                        relevance = self._calculate_relevance(line, keyword)
                        
                        # 获取上下文
                        context_start = max(0, i - 2)
                        context_end = min(len(lines), i + 3)
                        context = '\n'.join(lines[context_start:context_end])
                        
                        results.append(SearchResult(
                            file_path=str(md_file.relative_to(self.base_path)),
                            line_number=i + 1,
                            matched_text=line.strip(),
                            context=context,
                            relevance=relevance
                        ))
                        
            except Exception as e:
                logger.warning(f"Error searching file {md_file}: {e}")
        
        # 按相关度排序
        results.sort(key=lambda x: x.relevance, reverse=True)
        return results[:max_results]
    
    def _calculate_relevance(self, text: str, keyword: str) -> float:
        """计算相关度"""
        text_lower = text.lower()
        keyword_lower = keyword.lower()
        
        # 精确匹配加分
        score = 0.0
        if keyword_lower in text_lower:
            score += 0.5
            
        # 出现次数加分
        count = text_lower.count(keyword_lower)
        score += min(count * 0.1, 0.3)
        
        # 标题行加分（以#开头）
        if text.strip().startswith('#'):
            score += 0.2
        
        return min(score, 1.0)
    
    # ========== 链接处理 ==========
    
    def extract_wikilinks(self, content: str) -> List[LinkedContent]:
        """
        提取Wiki链接
        
        支持格式：
        - [[path]]
        - [[path|display_name]]
        - [[path#anchor]]
        - [[path#anchor|display_name]]
        
        Args:
            content: Markdown内容
            
        Returns:
            链接列表
        """
        # Wiki链接正则
        pattern = r'\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]'
        matches = re.findall(pattern, content)
        
        links = []
        for match in matches:
            path, anchor, display_name = match
            links.append(LinkedContent(
                source="",
                target=path.strip(),
                display_name=display_name.strip() if display_name else path.strip(),
                anchor=anchor.strip() if anchor else None,
            ))
        
        return links
    
    async def follow_links(
        self,
        relative_path: str,
        depth: int = 1
    ) -> List[LinkedContent]:
        """
        追踪文件中的所有链接
        
        Args:
            relative_path: 源文件路径
            depth: 追踪深度
            
        Returns:
            链接内容列表
        """
        if depth < 1:
            return []
        
        results = []
        content = await self.read_file(relative_path)
        links = self.extract_wikilinks(content)
        
        for link in links:
            link.source = relative_path
            
            # 尝试读取链接目标的内容
            try:
                target_content = await self.read_file(link.target)
                link.content_preview = target_content[:500]
                
                results.append(link)
                
                # 递归追踪（如果depth > 1）
                if depth > 1:
                    sub_links = await self.follow_links(link.target, depth - 1)
                    results.extend(sub_links)
                    
            except FileNotFoundError:
                logger.warning(f"Linked file not found: {link.target}")
        
        return results
    
    def resolve_link(
        self,
        link: str,
        source_path: Optional[str] = None
    ) -> str:
        """
        解析链接为绝对路径
        
        Args:
            link: Wiki链接
            source_path: 源文件路径（用于解析相对路径）
            
        Returns:
            解析后的路径（使用正斜杠）
        """
        # 提取路径部分
        match = re.match(r'\[\[([^\]|#]+)', link)
        if not match:
            return link
        
        target = match.group(1).strip()
        
        # 如果是绝对路径（以/开头），直接返回
        if target.startswith('/'):
            resolved_path = target[1:].replace(os.path.sep, '/')  # 去掉开头的/
        
        # 如果是相对路径，基于source_path解析
        elif source_path:
            # 构建源文件的父目录路径
            source_dir = os.path.dirname(source_path) if os.path.dirname(source_path) else '.'
            # 组合路径
            combined_path = os.path.normpath(os.path.join(source_dir, target))
            # 确保使用正斜杠
            resolved_path = combined_path.replace(os.path.sep, '/')

            # Fallback: if the resolved path doesn't exist, try resolving from KB root.
            # This handles the convention where '../' means "go to KB root" regardless of depth.
            if not self.file_exists(resolved_path):
                stripped = target
                while stripped.startswith('../'):
                    stripped = stripped[3:]
                if self.file_exists(stripped):
                    resolved_path = stripped
        
        # 如果没有source_path，直接返回target
        else:
            resolved_path = target.replace(os.path.sep, '/')
        
        return resolved_path
    
    # ========== 工具方法 ==========
    
    def list_files(
        self,
        directory: Optional[str] = None,
        include_details: bool = False,
        recursive: bool = False
    ) -> List[Dict[str, Any]]:
        """
        列出目录下的文件和子目录
        
        Args:
            directory: 目录路径
            include_details: 是否包含详细信息（名称、类型、修改时间等）
            recursive: 是否递归列出所有子目录
            
        Returns:
            文件和目录信息列表
        """
        import os
        from datetime import datetime
        
        search_path = self.base_path / directory if directory else self.base_path
        results = []
        
        # 构建路径遍历器
        if recursive:
            path_iter = search_path.rglob("*")
        else:
            path_iter = search_path.iterdir()
        
        for path in path_iter:
            relative_path = str(path.relative_to(self.base_path))
            
            if include_details:
                # 获取详细信息
                item_type = "directory" if path.is_dir() else "file"
                
                # 获取修改时间
                try:
                    modified_time = datetime.fromtimestamp(path.stat().st_mtime)
                except:
                    modified_time = None
                
                results.append({
                    "path": relative_path,
                    "name": path.name,
                    "type": item_type,
                    "modified": modified_time.isoformat() if modified_time else None,
                    "is_dir": path.is_dir(),
                    "is_file": path.is_file()
                })
            else:
                results.append(relative_path)
        
        return results
    
    def create_session_archive(self, session_data: dict) -> str:
        """创建采访记录归档文件。

        Args:
            session_data: 包含以下键的字典:
                summary, events, people, timepoints, next_questions,
                unfinished_topics, current_topic, emotion_state, topic_history

        Returns:
            创建的文件绝对路径
        """
        from datetime import datetime as _dt

        # Ensure sessions directory exists
        sessions_dir = self.base_path / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        date_str = _dt.now().strftime("%Y-%m-%d_%H-%M")
        file_name = f"session_{date_str}.md"
        file_path = sessions_dir / file_name

        # Build content
        summary = session_data.get("summary", "")
        events = session_data.get("events", [])
        people = session_data.get("people", [])
        timepoints = session_data.get("timepoints", [])
        next_questions = session_data.get("next_questions", [])
        unfinished_topics = session_data.get("unfinished_topics", "")
        current_topic = session_data.get("current_topic", "")
        emotion_state = session_data.get("emotion_state", "")
        topic_history = session_data.get("topic_history", [])

        # Format lists
        events_list = "\n".join(f"- {e}" for e in events) if events else "（无）"
        people_list = "\n".join(f"- {p}" for p in people) if people else "（无）"
        timepoints_list = "\n".join(f"- {t}" for t in timepoints) if timepoints else "（无）"
        questions_list = "\n".join(
            f"{i+1}. {q}" for i, q in enumerate(next_questions)
        ) if next_questions else "（无）"

        if isinstance(unfinished_topics, list):
            unfinished_text = "\n".join(f"- {t}" for t in unfinished_topics) if unfinished_topics else "（无）"
        else:
            unfinished_text = unfinished_topics or "（无）"

        if isinstance(topic_history, list):
            topic_history_text = "、".join(topic_history) if topic_history else "（无）"
        else:
            topic_history_text = topic_history or "（无）"

        content = f"""# 采访记录 - {date_str}

## 本次采访摘要
{summary}

## 收集的关键信息
### 事件
{events_list}

### 人物
{people_list}

### 时间点
{timepoints_list}

## 下次采访建议问题
{questions_list}

## 未完成的话题
{unfinished_text}

## 采访上下文
- 当前话题方向: {current_topic or '（无）'}
- 情绪状态: {emotion_state or '（无）'}
- 已探索话题: {topic_history_text}
"""

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Created session archive: {file_path}")
        return str(file_path)

    def file_exists(self, relative_path: str) -> bool:
        """检查文件是否存在"""
        return (self.base_path / relative_path).exists()
    
    def get_file_stats(self, relative_path: str) -> Dict[str, Any]:
        """获取文件统计信息"""
        file_path = self.base_path / relative_path
        
        if not file_path.exists():
            return {}
        
        stat = file_path.stat()
        return {
            "size": stat.st_size,
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
        }
