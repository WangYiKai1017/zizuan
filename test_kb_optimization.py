# test_kb_optimization.py
# 测试优化后的 KnowledgeBaseQuerier 功能

import asyncio
import logging
import os
import tempfile
import shutil
from dotenv import load_dotenv

from src.services.knowledge_base_querier import KnowledgeBaseQuerier
from src.storage.markdown_file_manager import MarkdownFileManager
from src.services.llm_service import LLMService
from src.config.llm_config import LLMConfig
from src.models import SessionState
from src.enums import StrategyType

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def setup_test_environment():
    """设置测试环境"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    logger.info(f"Created test directory: {temp_dir}")
    
    # 创建目录结构
    directories = [
        "events/childhood",
        "events/youth",
        "events/middle_age",
        "events/elderly",
        "people/family",
        "people/friends",
        "timeline",
        "themes"
    ]
    
    for dir_path in directories:
        os.makedirs(os.path.join(temp_dir, dir_path), exist_ok=True)
    
    # 创建文件管理器
    file_manager = MarkdownFileManager(base_path=temp_dir, conversation_id="test")
    
    # 创建测试文件
    test_files = {
        "events/childhood/birth.md": "# 出生\n我在1945年出生在上海，那时候的上海还是个小城市。\n",
        "events/childhood/school.md": "# 小学时光\n我在上海的一所小学上学，那时候的学校条件很艰苦。\n",
        "events/youth/university.md": "# 大学时光\n1968年，我从北京大学毕业，分配到一所中学当老师。\n",
        "events/youth/marriage.md": "# 恋爱结婚\n1970年，我和妻子结婚，我们是在工作中认识的。\n",
        "events/middle_age/career.md": "# 事业发展\n1980年代，我开始担任学校的教导主任，工作很忙碌。\n",
        "events/elderly/retirement.md": "# 退休生活\n2008年，我退休了，开始享受平静的晚年生活。\n",
        "people/family/wife.md": "# 妻子\n我的妻子叫王秀英，我们结婚50年了。\n",
        "people/family/children.md": "# 子女\n我有两个孩子，他们都很孝顺。\n",
        "people/friends/classmate.md": "# 大学同学\n我最好的朋友是大学同学李明，我们经常一起交流。\n",
        "timeline/life_events.md": "# 人生大事年表\n1945年：出生\n1968年：大学毕业\n1970年：结婚\n2008年：退休\n",
        "themes/values.md": "# 价值观\n我认为教育是最重要的，教师是最神圣的职业。\n"
    }
    
    # 使用file_manager创建文件，确保它们被创建在正确的位置
    for file_path, content in test_files.items():
        full_path = await file_manager.create_file(file_path, content)
        logger.info(f"Created test file: {full_path}")
    
    return temp_dir


async def test_knowledge_base_optimization():
    """测试优化后的KnowledgeBaseQuerier功能"""
    logger.info("开始测试优化后的KnowledgeBaseQuerier功能")
    
    try:
        # 设置测试环境
        temp_dir = await setup_test_environment()
        
        # 创建LLM配置
        llm_config = LLMConfig.from_env()
        llm_service = LLMService(llm_config)
        
        # 创建文件管理器
        file_manager = MarkdownFileManager(base_path=temp_dir, conversation_id="test")
        
        # 创建知识库查询器
        querier = KnowledgeBaseQuerier(file_manager, llm_service)
        
        # 创建会话状态
        session_state = SessionState(
            session_id="test_session",
            strategy=StrategyType.SPARKLE_FIRST
        )
        
        # 测试1：基本路径探索
        logger.info("\n=== 测试1：基本路径探索 ===")
        result = await querier.query(
            user_input="查找与退休相关的文件",
            target_path=os.path.join(temp_dir),
            state=session_state
        )
        logger.info(f"查询结果: {result.has_results}")
        logger.info(f"返回条目数: {result.total_count}")
        for entry in result.entries:
            logger.info(f"  - {entry.source}: {entry.content[:100]}...")
        
        # 测试2：深度路径探索
        logger.info("\n=== 测试2：深度路径探索 ===")
        result = await querier.query(
            user_input="查找所有与家庭相关的文件，包括子目录",
            target_path=os.path.join(temp_dir),
            state=session_state
        )
        logger.info(f"查询结果: {result.has_results}")
        logger.info(f"返回条目数: {result.total_count}")
        for entry in result.entries:
            logger.info(f"  - {entry.source}: {entry.content[:100]}...")
        
        # 测试3：未找到文件时的探索报告
        logger.info("\n=== 测试3：未找到文件时的探索报告 ===")
        result = await querier.query(
            user_input="查找与太空旅行相关的文件",
            target_path=os.path.join(temp_dir),
            state=session_state
        )
        logger.info(f"查询结果: {result.has_results}")
        logger.info(f"返回条目数: {result.total_count}")
        for entry in result.entries:
            logger.info(f"  - {entry.source}: {entry.content[:150]}...")
        
        # 测试4：智能文件访问控制
        logger.info("\n=== 测试4：智能文件访问控制 ===")
        result = await querier.query(
            user_input="查找关于人生大事的文件，并查看其内容",
            target_path=os.path.join(temp_dir),
            state=session_state
        )
        logger.info(f"查询结果: {result.has_results}")
        logger.info(f"返回条目数: {result.total_count}")
        for entry in result.entries:
            logger.info(f"  - {entry.source}: {entry.content[:100]}...")
        
        # 清理测试环境
        shutil.rmtree(temp_dir)
        logger.info(f"Cleaned up test directory: {temp_dir}")
        
        logger.info("\n优化后的KnowledgeBaseQuerier功能测试完成！")
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行测试"""
    result = await test_knowledge_base_optimization()
    if result:
        logger.info("所有测试通过！")
    else:
        logger.error("测试失败！")


if __name__ == "__main__":
    asyncio.run(main())