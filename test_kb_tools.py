# test_kb_tools.py
# 直接测试优化后的KnowledgeBaseTools功能

import asyncio
import logging
import os
import tempfile
import shutil
from src.services.knowledge_base_querier import KnowledgeBaseTools
from src.storage.markdown_file_manager import MarkdownFileManager

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def setup_test_environment():
    """设置测试环境"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    logger.info(f"Created test directory: {temp_dir}")
    
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
    
    # 使用file_manager创建文件
    for file_path, content in test_files.items():
        full_path = await file_manager.create_file(file_path, content)
        logger.info(f"Created test file: {full_path}")
    
    return temp_dir, file_manager


async def test_knowledge_base_tools():
    """测试优化后的KnowledgeBaseTools功能"""
    logger.info("开始测试优化后的KnowledgeBaseTools功能")
    
    try:
        # 设置测试环境
        temp_dir, file_manager = await setup_test_environment()
        
        # 创建KnowledgeBaseTools实例
        tools = KnowledgeBaseTools(file_manager)
        
        # 设置目标路径
        target_path = os.path.join(temp_dir, "test")  # 注意：file_manager会在base_path下创建conversation_id目录
        tools.set_target_path(target_path)
        logger.info(f"Set target path: {target_path}")
        
        # 测试1：基本路径探索
        logger.info("\n=== 测试1：基本路径探索 ===")
        list_files_tool = tools.tools[0]  # 获取list_files工具
        result = list_files_tool.invoke({"path": "", "recursive": False})
        logger.info(f"List files result (root): {result}")
        
        # 测试2：深度路径探索
        logger.info("\n=== 测试2：深度路径探索 ===")
        result = list_files_tool.invoke({"path": "events", "recursive": True})
        logger.info(f"List files result (events recursive): {result}")
        
        # 测试3：路径记忆功能
        logger.info("\n=== 测试3：路径记忆功能 ===")
        logger.info(f"Visited paths: {tools._visited_paths}")
        
        # 测试4：标记疑似文件
        logger.info("\n=== 测试4：标记疑似文件 ===")
        mark_tool = [t for t in tools.tools if t.name == "mark_suspected_file"][0]
        result = mark_tool.invoke({"file_path": "timeline/life_events.md"})
        logger.info(f"Mark suspected file result: {result}")
        logger.info(f"Suspected files: {tools._suspected_files}")
        
        # 测试5：检查路径是否已访问
        logger.info("\n=== 测试5：检查路径是否已访问 ===")
        has_visited_tool = [t for t in tools.tools if t.name == "has_visited"][0]
        result = has_visited_tool.invoke({"path": "events"})
        logger.info(f"Has visited 'events': {result}")
        
        result = has_visited_tool.invoke({"path": "nonexistent"})
        logger.info(f"Has visited 'nonexistent': {result}")
        
        # 测试6：获取探索报告
        logger.info("\n=== 测试6：获取探索报告 ===")
        report_tool = [t for t in tools.tools if t.name == "get_exploration_report"][0]
        result = report_tool.invoke({})
        logger.info(f"Exploration report: {result}")
        
        # 测试7：重置访问记录
        logger.info("\n=== 测试7：重置访问记录 ===")
        tools._visited_paths.clear()
        tools._suspected_files.clear()
        logger.info(f"Visited paths after clear: {tools._visited_paths}")
        logger.info(f"Suspected files after clear: {tools._suspected_files}")
        
        # 清理测试环境
        shutil.rmtree(temp_dir)
        logger.info(f"Cleaned up test directory: {temp_dir}")
        
        logger.info("\n优化后的KnowledgeBaseTools功能测试完成！")
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行测试"""
    result = await test_knowledge_base_tools()
    if result:
        logger.info("所有测试通过！")
    else:
        logger.error("测试失败！")


if __name__ == "__main__":
    asyncio.run(main())