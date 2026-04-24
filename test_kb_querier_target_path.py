# test_kb_querier_target_path.py
# 测试 KnowledgeBaseQuerier 的 target_path 参数功能

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

async def test_knowledge_base_querier_with_target_path():
    """测试KnowledgeBaseQuerier的target_path参数"""
    logger.info("开始测试KnowledgeBaseQuerier的target_path参数")
    
    try:
        # 设置测试环境
        temp_dir = "C:\\Users\\MSI\\AppData\\Local\\Temp\\memory\\a598d251"
        
        # 创建LLM配置
        llm_config = LLMConfig.from_env()
        llm_service = LLMService(llm_config)
        
        # 创建文件管理器
        file_manager = MarkdownFileManager(base_path=temp_dir, conversation_id="a598d251")
        
        # 创建知识库查询器
        querier = KnowledgeBaseQuerier(file_manager, llm_service)
        
        # 创建会话状态
        session_state = SessionState(
            session_id="test_session",
            strategy=StrategyType.SPARKLE_FIRST
        )
        
        # 测试1：正常查询 - 限定在events/childhood目录
        logger.info("\n=== 测试1：正常查询 - 限定在events/childhood目录 ===")
        result = await querier.query(
            user_input="我家里有哪些成员？",
            target_path=os.path.join(temp_dir, ""),
            state=session_state
        )
        logger.info(f"查询结果: {result.has_results}")
        logger.info(f"返回条目数: {result.total_count}")
        logger.info(f"详情: {result.linked_content}")
        logger.info(f"详情: {result.entries}")
        for entry in result.entries:
            logger.info(f"  - {entry.source}: {entry.content}")
        
        # # 测试2：目录遍历攻击防护
        # logger.info("\n=== 测试2：目录遍历攻击防护 ===")
        # result = await querier.query(
        #     user_input="我的家人情况如何？",
        #     target_path=os.path.join(temp_dir, "events/childhood"),
        #     state=session_state
        # )
        # logger.info(f"查询结果: {result.has_results}")
        # logger.info(f"返回条目数: {result.total_count}")
        # for entry in result.entries:
        #     logger.info(f"  - {entry.source}: {entry.content[:50]}...")
        
        # # 测试3：限定在people目录
        # logger.info("\n=== 测试3：限定在people目录 ===")
        # result = await querier.query(
        #     user_input="我的家人和朋友情况如何？",
        #     target_path=os.path.join(temp_dir, "people"),
        #     state=session_state
        # )
        # logger.info(f"查询结果: {result.has_results}")
        # logger.info(f"返回条目数: {result.total_count}")
        # for entry in result.entries:
        #     logger.info(f"  - {entry.source}: {entry.content[:50]}...")
        
        # # 测试4：无效路径
        # logger.info("\n=== 测试4：无效路径 ===")
        # result = await querier.query(
        #     user_input="我的家人情况如何？",
        #     target_path=os.path.join(temp_dir, "nonexistent"),
        #     state=session_state
        # )
        # logger.info(f"查询结果: {result.has_results}")
        # logger.info(f"返回条目数: {result.total_count}")
        
        # 清理测试环境
        # shutil.rmtree(temp_dir)
        # logger.info(f"Cleaned up test directory: {temp_dir}")
        
        logger.info("\nKnowledgeBaseQuerier的target_path参数测试完成！")
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行测试"""
    result = await test_knowledge_base_querier_with_target_path()
    if result:
        logger.info("所有测试通过！")
    else:
        logger.error("测试失败！")


if __name__ == "__main__":
    asyncio.run(main())