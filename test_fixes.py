import unittest
import asyncio
import os
import tempfile
from pathlib import Path

from src.agents.interview_agent import InterviewAgent
from src.storage.markdown_file_manager import MarkdownFileManager
from src.services.llm_service import get_llm_service


class TestInterviewAgentFixes(unittest.TestCase):
    """测试InterviewAgent的修复"""
    
    def setUp(self):
        self.llm_service = get_llm_service()
        self.user_id = "test_user_001"
    
    def test_start_method_unified_initialization(self):
        """测试start()方法的统一初始化逻辑"""
        # 创建没有resume_context的Agent（新用户）
        agent = InterviewAgent(user_id=self.user_id, llm_service=self.llm_service)

        # 确保resume_context为空
        self.assertEqual(agent.resume_context, {})

        # 运行start方法
        opening = asyncio.run(agent.start())

        # 验证返回结果
        self.assertIsInstance(opening, str)
        self.assertGreater(len(opening), 0)

        # 创建有resume_context的Agent（老用户）
        custom_context = {"summary": "上次聊了童年的事"}
        agent2 = InterviewAgent(user_id=self.user_id, llm_service=self.llm_service, resume_context=custom_context)

        # 运行start方法
        opening2 = asyncio.run(agent2.start())

        # 验证返回结果
        self.assertIsInstance(opening2, str)
        self.assertGreater(len(opening2), 0)


class TestMarkdownFileManagerFixes(unittest.TestCase):
    """测试MarkdownFileManager的修复"""
    
    def setUp(self):
        # 创建临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.file_manager = MarkdownFileManager(base_path=self.temp_dir, conversation_id='test')
    
    def tearDown(self):
        # 清理临时目录
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_file_conflict_handling(self):
        """测试文件冲突处理机制"""
        # 创建测试文件
        test_path = "test_file.md"
        content1 = "# 测试文件内容1"
        content2 = "\n## 新增内容"
        
        # 首次创建文件
        asyncio.run(self.file_manager.create_file(test_path, content1))
        
        # 验证文件内容
        file_content = asyncio.run(self.file_manager.read_file(test_path))
        self.assertEqual(file_content, content1)
        
        # 再次创建相同文件，不允许覆盖
        asyncio.run(self.file_manager.create_file(test_path, content2, overwrite=False))
        
        # 验证文件内容已追加
        file_content = asyncio.run(self.file_manager.read_file(test_path))
        self.assertEqual(file_content, content1 + "\n" + content2)
        
        # 再次创建相同文件，允许覆盖
        content3 = "# 全新内容"
        asyncio.run(self.file_manager.create_file(test_path, content3, overwrite=True))
        
        # 验证文件内容已覆盖
        file_content = asyncio.run(self.file_manager.read_file(test_path))
        self.assertEqual(file_content, content3)
    
    def test_link_resolution(self):
        """测试文档链接解析功能"""
        # 测试绝对路径链接
        link1 = "[[/events/childhood/童年回忆.md]]"
        resolved1 = self.file_manager.resolve_link(link1)
        self.assertEqual(resolved1, "events/childhood/童年回忆.md")
        
        # 测试相对路径链接
        link2 = "[[../people/family/父亲.md]]"
        resolved2 = self.file_manager.resolve_link(link2, source_path="events/childhood/童年回忆.md")
        self.assertEqual(resolved2, "events/people/family/父亲.md")
        
        # 测试从根目录开始的相对路径
        link3 = "[[../../people/family/父亲.md]]"
        resolved3 = self.file_manager.resolve_link(link3, source_path="events/childhood/1950s/童年回忆.md")
        self.assertEqual(resolved3, "events/people/family/父亲.md")
        
        # 测试外部链接处理
        link4 = "[[../../external_file.md]]"
        resolved4 = self.file_manager.resolve_link(link4, source_path="events/childhood/童年回忆.md")
        # 实际解析结果会是相对于根目录的路径
        self.assertEqual(resolved4, "external_file.md")


if __name__ == "__main__":
    unittest.main()