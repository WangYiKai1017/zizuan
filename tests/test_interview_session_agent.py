import pytest
import tempfile
import os
from pathlib import Path
from src.agents.interview_session_agent import InterviewSessionAgent
from src.storage.markdown_file_manager import MarkdownFileManager


class TestInterviewSessionAgent:
    @pytest.fixture
    def temp_knowledge_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir
    
    @pytest.mark.asyncio
    async def test_check_knowledge_base(self, temp_knowledge_base):
        # 创建用户ID
        user_id = "test_user"
        
        # 初始化InterviewSessionAgent
        agent = InterviewSessionAgent(user_id)
        
        # 修改知识库路径以使用临时目录
        agent.knowledge_base_root = Path(temp_knowledge_base)
        agent.knowledge_base_path = agent.knowledge_base_root / user_id
        
        # 测试1：知识库目录不存在
        exists = await agent._check_knowledge_base()
        assert exists is False
        
        # 测试2：创建知识库目录但结构不完整
        agent.knowledge_base_path.mkdir(parents=True)
        
        exists = await agent._check_knowledge_base()
        assert exists is False
        
        # 测试3：创建完整的目录结构但只有index.md文件
        required_directories = [
            "events/childhood",
            "events/youth",
            "events/middle_age",
            "events/elderly",
            "people/family",
            "people/friends",
            "people/colleagues",
            "people/others",
            "timeline",
            "themes"
        ]
        
        for dir_name in required_directories:
            dir_path = agent.knowledge_base_path / dir_name
            dir_path.mkdir(parents=True)
        
        # 创建index.md文件
        index_path = agent.knowledge_base_path / "index.md"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# 记忆库索引")
        
        exists = await agent._check_knowledge_base()
        assert exists is False
        
        # 测试4：创建完整的目录结构并添加其他Markdown文件
        # 创建一个测试人物文件
        person_path = agent.knowledge_base_path / "people/protagonist.md"
        with open(person_path, "w", encoding="utf-8") as f:
            f.write("# 主人公信息")
        
        exists = await agent._check_knowledge_base()
        assert exists is True
        
        # 测试5：异常情况测试
        # 将知识库路径设置为一个不存在的目录
        agent.knowledge_base_path = agent.knowledge_base_root / "non_existent_user"
        
        exists = await agent._check_knowledge_base()
        assert exists is False