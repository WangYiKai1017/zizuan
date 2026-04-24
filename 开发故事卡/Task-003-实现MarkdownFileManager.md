# 开发故事卡 - Task 3: 实现MarkdownFileManager

> 任务编号：Task-003  
> 优先级：P0  
> 依赖：Task-001（数据对象）  
> 预计工时：0.5天

---

## 一、任务概述

实现MarkdownFileManager，负责管理md格式的记忆库文件系统，包括文件的创建、读取、更新、搜索，以及Wiki风格链接的追踪。

---

## 二、项目上下文

### 2.1 记忆库文件结构

```
memory/
├── events/                    # 事件记忆库
│   ├── childhood/             # 童年事件
│   │   ├── birth-family.md
│   │   ├── early-memory.md
│   │   └── ...
│   ├── youth/                 # 少年事件
│   ├── middle_age/            # 中年事件
│   └── elderly/               # 老年事件
│
├── people/                    # 人物画像库
│   ├── protagonist.md         # 主人公
│   ├── family/
│   │   ├── father.md
│   │   ├── mother.md
│   │   └── ...
│   └── colleagues/
│
├── timeline/                  # 时间线库
│   ├── life-events.md
│   └── detailed-timeline.md
│
├── themes/                    # 主题记忆库
│   ├── values.md
│   └── turning-points.md
│
└── index.md                   # 总索引
```

### 2.2 Wiki链接格式

```markdown
# 使用相对路径的Wiki链接
- [[../people/family/father.md|父亲]]：张大明，纺织厂工人
- [[../events/childhood/birth-family.md|出生家庭]]
- [[../timeline/life-events.md#1970|人生大事年表 - 1970年]]

# 链接解析：
# [[路径|显示名称]]
# [[路径#锚点|显示名称]]
```

---

## 三、详细设计

```python
# src/storage/markdown_file_manager.py
import os
import re
import aiofiles
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
    
    def __init__(self, base_path: str = "memory"):
        """
        初始化
        
        Args:
            base_path: 记忆库根目录
        """
        self.base_path = Path(base_path)
        self._ensure_directory_structure()
    
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
        
        if file_path.exists() and not overwrite:
            logger.warning(f"File already exists: {file_path}")
            return str(file_path)
        
        # 确保父目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
            await f.write(content)
        
        logger.info(f"Created file: {file_path}")
        return str(file_path)
    
    async def read_file(self, relative_path: str) -> str:
        """
        读取md文件
        
        Args:
            relative_path: 相对路径
            
        Returns:
            文件内容
        """
        file_path = self.base_path / relative_path
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
            content = await f.read()
        
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
            解析后的路径
        """
        # 提取路径部分
        match = re.match(r'\[\[([^\]|#]+)', link)
        if not match:
            return link
        
        target = match.group(1).strip()
        
        # 如果是相对路径，基于source_path解析
        if source_path and not target.startswith('/'):
            source_dir = Path(source_path).parent
            resolved = (self.base_path / source_dir / target).resolve()
            return str(resolved.relative_to(self.base_path))
        
        return target
    
    # ========== 工具方法 ==========
    
    def list_files(
        self,
        directory: Optional[str] = None,
        pattern: str = "*.md"
    ) -> List[str]:
        """
        列出目录下的文件
        
        Args:
            directory: 目录路径
            pattern: 文件匹配模式
            
        Returns:
            文件路径列表
        """
        search_path = self.base_path / directory if directory else self.base_path
        return [str(f.relative_to(self.base_path)) for f in search_path.rglob(pattern)]
    
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
```

---

## 四、开发要求

### 4.1 代码规范

```python
# 1. 所有IO操作使用async/await
async def read_file(self, path: str) -> str:
    async with aiofiles.open(...) as f:
        return await f.read()

# 2. 使用Path处理路径
from pathlib import Path
file_path = self.base_path / relative_path

# 3. 异常处理要具体
except FileNotFoundError:
    # 文件不存在
except PermissionError:
    # 权限错误

# 4. 日志记录关键操作
logger.info(f"Created file: {file_path}")
```

### 4.2 单元测试要求

```python
# tests/test_markdown_file_manager.py
import pytest
import tempfile
from storage.markdown_file_manager import MarkdownFileManager

class TestMarkdownFileManager:
    @pytest.fixture
    async def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield MarkdownFileManager(tmpdir)
    
    @pytest.mark.asyncio
    async def test_create_file(self, manager):
        """测试创建文件"""
        path = await manager.create_file(
            "events/test.md",
            "# Test\n\nContent"
        )
        
        assert manager.file_exists("events/test.md")
    
    @pytest.mark.asyncio
    async def test_read_file(self, manager):
        """测试读取文件"""
        await manager.create_file("test.md", "Hello")
        
        content = await manager.read_file("test.md")
        assert content == "Hello"
    
    @pytest.mark.asyncio
    async def test_search_files(self, manager):
        """测试搜索"""
        await manager.create_file("a.md", "Hello World")
        await manager.create_file("b.md", "Hello Python")
        
        results = await manager.search_files("Hello")
        assert len(results) == 2
    
    def test_extract_wikilinks(self, manager):
        """测试链接提取"""
        content = "[[../people/father.md|父亲]] and [[events/birth]]"
        links = manager.extract_wikilinks(content)
        
        assert len(links) == 2
        assert links[0].target == "../people/father.md"
        assert links[0].display_name == "父亲"
```

### 4.3 验收标准

- [ ] MarkdownFileManager实现完成
- [ ] 支持创建、读取、更新文件
- [ ] 全文搜索功能正常
- [ ] Wiki链接提取和追踪正常
- [ ] 单元测试覆盖率 > 80%
- [ ] 异步IO正常工作

---

## 五、参考资源

- [Python pathlib文档](https://docs.python.org/3/library/pathlib.html)
- [aiofiles文档](https://github.com/Tinche/aiofiles)
