# test_read_file.py
# 专门测试read_file工具的功能

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
        "events/youth/university.md": "# 大学时光\n1968年，我从北京大学毕业，分配到一所中学当老师。\n",
        "timeline/life_events.md": "# 人生大事年表\n1945年：出生\n1968年：大学毕业\n1970年：结婚\n2008年：退休\n",
    }
    
    # 使用file_manager创建文件
    for file_path, content in test_files.items():
        full_path = await file_manager.create_file(file_path, content)
        logger.info(f"Created test file: {full_path}")
    
    return temp_dir, file_manager


async def test_read_file_tool():
    """测试read_file工具的功能"""
    logger.info("开始测试read_file工具的功能")
    
    try:
        # 设置测试环境
        temp_dir, file_manager = await setup_test_environment()
        
        # 创建KnowledgeBaseTools实例
        tools = KnowledgeBaseTools(file_manager)
        
        # 设置目标路径
        target_path = os.path.join(temp_dir, "test")
        tools.set_target_path(target_path)
        logger.info(f"Set target path: {target_path}")
        
        # 获取read_file工具
        read_file_tool = [t for t in tools.tools if t.name == "read_file"][0]
        
        # 测试读取存在的文件
        logger.info("\n=== 测试1：读取存在的文件 ===")
        result = read_file_tool.invoke({"file_path": "events/childhood/birth.md"})
        logger.info(f"Read file result: {result}")
        assert "出生" in result, "File content should contain '出生'"
        assert "1945" in result, "File content should contain '1945'"
        
        # 测试读取另一个文件
        logger.info("\n=== 测试2：读取另一个存在的文件 ===")
        result = read_file_tool.invoke({"file_path": "timeline/life_events.md"})
        logger.info(f"Read file result: {result}")
        assert "人生大事年表" in result, "File content should contain '人生大事年表'"
        assert "1968" in result, "File content should contain '1968'"
        assert "2008" in result, "File content should contain '2008'"
        
        # 测试读取不存在的文件
        logger.info("\n=== 测试3：读取不存在的文件 ===")
        result = read_file_tool.invoke({"file_path": "nonexistent/file.md"})
        logger.info(f"Read file result: {result}")
        assert "无法读取文件" in result, "Should return error message for non-existent file"
        
        # 测试读取目录（应该失败）
        logger.info("\n=== 测试4：读取目录 ===")
        result = read_file_tool.invoke({"file_path": "events"})
        logger.info(f"Read file result: {result}")
        assert "无法读取文件" in result, "Should return error message for directory"
        
        # 清理测试环境
        shutil.rmtree(temp_dir)
        logger.info(f"Cleaned up test directory: {temp_dir}")
        
        logger.info("\nread_file工具功能测试完成！")
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行测试"""
    result = await test_read_file_tool()
    if result:
        logger.info("所有测试通过！")
    else:
        logger.error("测试失败！")


if __name__ == "__main__":
    asyncio.run(main())