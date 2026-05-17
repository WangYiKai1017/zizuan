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
        content = """# 记忆库索引

## 事件
- [童年事件](events/childhood/)
- [少年事件](events/youth/)
- [中年事件](events/middle_age/)
- [老年事件](events/elderly/)

## 人物
- [主人公](people/protagonist.md)
- [家庭成员](people/family/)
- [朋友](people/friends/)
- [同事](people/colleagues/)
- [其他](people/others/)

## 时间线
- [人生大事年表](timeline/life-events.md)

## 主题
- [价值观形成](themes/values.md)
- [人生转折点](themes/turning-points.md)
"""
        index_path = self.base_path / "index.md"
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
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