# test_kb_adjustments.py
# 测试知识库检索器的调整功能

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


async def test_path_priority_exploration():
    """测试路径优先级探索机制"""
    logger.info("\n=== 测试1：路径优先级探索机制 ===")
    
    try:
        # 设置测试环境
        temp_dir, file_manager = await setup_test_environment()
        
        # 创建KnowledgeBaseTools实例
        tools = KnowledgeBaseTools(file_manager)
        
        # 设置目标路径
        target_path = os.path.join(temp_dir, "test")
        tools.set_target_path(target_path)
        logger.info(f"Set target path: {target_path}")
        
        # 获取list_files工具
        list_files_tool = [t for t in tools.tools if t.name == "list_files"][0]
        
        # 测试默认递归列出所有层级目录信息
        result = list_files_tool.invoke({"path": "", "recursive": True})
        logger.info(f"List files (default recursive) result contains {len(result.splitlines())} lines")
        
        # 添加调试信息，显示返回结果的前50行
        logger.info("Result preview:")
        for i, line in enumerate(result.splitlines()[:50]):
            logger.info(f"  {i+1}: {line}")
        
        # 验证返回的内容包含所有层级的文件
        # 直接检查"birth.md"、"retirement.md"、"wife.md"等文件名是否存在，而不是完整路径
        assert "birth.md" in result, "Should contain birth.md"
        assert "retirement.md" in result, "Should contain retirement.md"
        assert "wife.md" in result, "Should contain wife.md"
        
        # 验证结果是排序的（目录优先）
        lines = result.splitlines()
        first_directory_found = False
        first_file_found = False
        for line in lines:
            if '"type": "directory"' in line:
                first_directory_found = True
            elif '"type": "file"' in line:
                first_file_found = True
                # 验证目录出现在文件之前
                assert first_directory_found, "Directories should be listed before files"
                break
        
        logger.info("✅ 路径优先级探索机制测试通过")
        
        # 清理测试环境
        shutil.rmtree(temp_dir)
        logger.info(f"Cleaned up test directory: {temp_dir}")
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_document_processing_flow():
    """测试文档处理流程"""
    logger.info("\n=== 测试2：文档处理流程 ===")
    
    try:
        # 设置测试环境
        temp_dir, file_manager = await setup_test_environment()
        
        # 创建KnowledgeBaseTools实例
        tools = KnowledgeBaseTools(file_manager)
        
        # 设置目标路径
        target_path = os.path.join(temp_dir, "test")
        tools.set_target_path(target_path)
        
        # 获取read_file工具
        read_file_tool = [t for t in tools.tools if t.name == "read_file"][0]
        
        # 测试读取完整文档内容
        result = read_file_tool.invoke({"file_path": "timeline/life_events.md"})
        logger.info(f"Read file result: {result}")
        
        # 验证返回的是完整内容
        assert "# 人生大事年表" in result, "Should contain full content"
        assert "1945年：出生" in result, "Should contain full content"
        assert "1968年：大学毕业" in result, "Should contain full content"
        assert "1970年：结婚" in result, "Should contain full content"
        assert "2008年：退休" in result, "Should contain full content"
        
        logger.info("✅ 文档处理流程测试通过")
        
        # 清理测试环境
        shutil.rmtree(temp_dir)
        logger.info(f"Cleaned up test directory: {temp_dir}")
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_search_function_disabled():
    """测试搜索功能是否被禁用"""
    logger.info("\n=== 测试3：搜索功能禁用 ===")
    
    try:
        # 设置测试环境
        temp_dir, file_manager = await setup_test_environment()
        
        # 创建KnowledgeBaseTools实例
        tools = KnowledgeBaseTools(file_manager)
        
        # 检查搜索功能是否被禁用
        tool_names = [t.name for t in tools.tools]
        logger.info(f"Available tools: {tool_names}")
        
        # 验证search_content工具不在可用工具列表中
        assert "search_content" not in tool_names, "search_content should be disabled"
        
        logger.info("✅ 搜索功能禁用测试通过")
        
        # 清理测试环境
        shutil.rmtree(temp_dir)
        logger.info(f"Cleaned up test directory: {temp_dir}")
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行所有测试"""
    logger.info("开始测试知识库检索器的调整功能")
    
    # 运行测试
    tests = [
        test_path_priority_exploration,
        test_document_processing_flow,
        test_search_function_disabled
    ]
    
    results = []
    for test in tests:
        result = await test()
        results.append(result)
    
    # 汇总结果
    logger.info(f"\n测试完成！通过: {sum(results)}/{len(results)}")
    
    if all(results):
        logger.info("✅ 所有测试通过！")
        return True
    else:
        logger.error("❌ 部分测试失败！")
        return False


if __name__ == "__main__":
    asyncio.run(main())