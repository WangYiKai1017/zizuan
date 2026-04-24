import pytest
import tempfile
import os
from src.storage.markdown_file_manager import MarkdownFileManager


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
    async def test_create_file_overwrite(self, manager):
        """测试覆盖文件"""
        await manager.create_file("test.md", "Original")
        await manager.create_file("test.md", "Overwritten", overwrite=True)
        
        content = await manager.read_file("test.md")
        assert content == "Overwritten"
    
    @pytest.mark.asyncio
    async def test_read_file(self, manager):
        """测试读取文件"""
        await manager.create_file("test.md", "Hello")
        
        content = await manager.read_file("test.md")
        assert content == "Hello"
    
    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, manager):
        """测试读取不存在的文件"""
        with pytest.raises(FileNotFoundError):
            await manager.read_file("nonexistent.md")
    
    @pytest.mark.asyncio
    async def test_update_file(self, manager):
        """测试更新文件"""
        await manager.create_file("test.md", "Original")
        await manager.update_file("test.md", "Updated")
        
        content = await manager.read_file("test.md")
        assert content == "Updated"
    
    @pytest.mark.asyncio
    async def test_update_nonexistent_file(self, manager):
        """测试更新不存在的文件（应该创建）"""
        await manager.update_file("new.md", "Content")
        
        assert manager.file_exists("new.md")
        content = await manager.read_file("new.md")
        assert content == "Content"
    
    @pytest.mark.asyncio
    async def test_update_file_append(self, manager):
        """测试追加文件内容"""
        await manager.create_file("test.md", "Line 1")
        await manager.update_file("test.md", "Line 2", append=True)
        
        content = await manager.read_file("test.md")
        assert content == "Line 1\nLine 2"
    
    @pytest.mark.asyncio
    async def test_append_section(self, manager):
        """测试追加章节"""
        await manager.create_file("test.md", "# Main Title")
        await manager.append_section("test.md", "Section 1", "Section content")
        
        content = await manager.read_file("test.md")
        assert "## Section 1" in content
        assert "Section content" in content
    
    @pytest.mark.asyncio
    async def test_search_files(self, manager):
        """测试搜索"""
        await manager.create_file("a.md", "Hello World")
        await manager.create_file("b.md", "Hello Python")
        await manager.create_file("c.md", "Hi there")
        
        results = await manager.search_files("Hello")
        assert len(results) == 2
        assert any("Hello World" in r.matched_text for r in results)
        assert any("Hello Python" in r.matched_text for r in results)
    
    @pytest.mark.asyncio
    async def test_search_files_case_insensitive(self, manager):
        """测试不区分大小写的搜索"""
        await manager.create_file("test.md", "Hello World")
        
        results = await manager.search_files("hello")
        assert len(results) == 1
        
        results = await manager.search_files("WORLD")
        assert len(results) == 1
    
    @pytest.mark.asyncio
    async def test_search_files_with_context(self, manager):
        """测试搜索结果包含上下文"""
        content = "Line 1\nLine 2 with keyword\nLine 3\nLine 4"
        await manager.create_file("test.md", content)
        
        results = await manager.search_files("keyword")
        assert len(results) == 1
        assert "Line 1" in results[0].context
        assert "Line 2 with keyword" in results[0].context
        assert "Line 3" in results[0].context
    
    def test_extract_wikilinks(self, manager):
        """测试链接提取"""
        content = "[[../people/father.md|父亲]] and [[events/birth]]"
        links = manager.extract_wikilinks(content)
        
        assert len(links) == 2
        assert links[0].target == "../people/father.md"
        assert links[0].display_name == "父亲"
        assert links[1].target == "events/birth"
        assert links[1].display_name == "events/birth"
    
    def test_extract_wikilinks_with_anchor(self, manager):
        """测试提取带锚点的链接"""
        content = "[[timeline.md#1970|1970年]]"
        links = manager.extract_wikilinks(content)
        
        assert len(links) == 1
        assert links[0].target == "timeline.md"
        assert links[0].anchor == "1970"
        assert links[0].display_name == "1970年"
    
    def test_resolve_link(self, manager):
        """测试解析链接"""
        # 测试相对路径解析 (../events/test.md 从 people/family/father.md 解析)
        resolved = manager.resolve_link("[[../events/test.md|Test]]", "people/family/father.md")
        assert resolved == "people/events/test.md"
        
        # 测试双级相对路径解析 (../../events/test.md 从 people/family/father.md 解析)
        resolved = manager.resolve_link("[[../../events/test.md|Test]]", "people/family/father.md")
        assert resolved == "events/test.md"
        
        # 测试绝对路径
        resolved = manager.resolve_link("[[/events/test.md|Test]]")
        assert resolved == "events/test.md"
        
        # 测试无效链接
        resolved = manager.resolve_link("not a link")
        assert resolved == "not a link"
    
    @pytest.mark.asyncio
    async def test_follow_links(self, manager):
        """测试追踪链接"""
        # 创建两个链接的文件
        await manager.create_file("page1.md", "Link to [[page2.md|Page 2]]")
        await manager.create_file("page2.md", "Content of page 2")
        
        links = await manager.follow_links("page1.md")
        
        assert len(links) == 1
        assert links[0].source == "page1.md"
        assert links[0].target == "page2.md"
        assert links[0].display_name == "Page 2"
        assert "Content of page 2" in links[0].content_preview
    
    @pytest.mark.asyncio
    async def test_follow_links_with_depth(self, manager):
        """测试追踪链接的深度"""
        await manager.create_file("page1.md", "Link to [[page2.md]]")
        await manager.create_file("page2.md", "Link to [[page3.md]]")
        await manager.create_file("page3.md", "Content")
        
        # 深度1
        links1 = await manager.follow_links("page1.md", depth=1)
        assert len(links1) == 1
        
        # 深度2
        links2 = await manager.follow_links("page1.md", depth=2)
        assert len(links2) == 2
    
    def test_list_files(self, manager):
        """测试列出文件"""
        # 目录结构应该已经创建
        files = manager.list_files()
        assert "index.md" in files
    
    def test_file_exists(self, manager):
        """测试文件存在检查"""
        assert manager.file_exists("index.md")  # 索引文件应该存在
        assert not manager.file_exists("nonexistent.md")
    
    def test_get_file_stats(self, manager):
        """测试获取文件统计信息"""
        stats = manager.get_file_stats("index.md")
        assert "size" in stats
        assert "created" in stats
        assert "modified" in stats
        
        # 不存在的文件返回空字典
        stats = manager.get_file_stats("nonexistent.md")
        assert stats == {}