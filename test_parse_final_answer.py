# test_parse_final_answer.py
# 测试_parse_final_answer方法的兼容性适配

import logging
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.knowledge_base_querier import KnowledgeBaseQuerier
from src.storage.markdown_file_manager import MarkdownFileManager

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def setup_test_environment():
    """设置测试环境"""
    # 创建临时目录
    import tempfile
    temp_dir = tempfile.mkdtemp()
    logger.info(f"Created test directory: {temp_dir}")
    
    # 创建文件管理器
    file_manager = MarkdownFileManager(base_path=temp_dir, conversation_id="test")
    
    # 创建知识库查询器
    querier = KnowledgeBaseQuerier(file_manager)
    
    return querier, temp_dir


async def test_parse_json_format():
    """测试解析标准JSON格式输出"""
    logger.info("\n=== 测试1：解析标准JSON格式输出 ===")
    
    try:
        querier, temp_dir = await setup_test_environment()
        
        # 标准JSON格式输出
        json_output = """
Final Answer:
{
  "query_intent": "查询家庭成员信息",
  "related_memories": [
    {
      "source": "people/family/wife.md",
      "content": "我的妻子叫王秀英，我们结婚50年了。",
      "relevance": "直接相关",
      "memory_type": "long_term"
    },
    {
      "source": "people/family/children.md",
      "content": "我有两个孩子，他们都很孝顺。",
      "relevance": "直接相关",
      "memory_type": "long_term"
    }
  ],
  "linked_context": [],
  "search_summary": "找到了2个相关文件"
}
"""
        
        result = querier._parse_final_answer(json_output)
        logger.info(f"解析结果: {result}")
        
        # 验证解析结果
        assert "related_memories" in result, "Should have related_memories"
        assert len(result["related_memories"]) == 2, "Should have 2 memories"
        assert result["related_memories"][0]["source"] == "people/family/wife.md", "Should have correct source"
        assert result["related_memories"][0]["content"] == "我的妻子叫王秀英，我们结婚50年了。", "Should have correct content"
        
        logger.info("✅ 标准JSON格式解析测试通过")
        
        # 清理测试环境
        import shutil
        shutil.rmtree(temp_dir)
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_parse_natural_language():
    """测试解析自然语言描述输出"""
    logger.info("\n=== 测试2：解析自然语言描述输出 ===")
    
    try:
        querier, temp_dir = await setup_test_environment()
        
        # 自然语言描述输出
        natural_output = """
我已经找到了关于家庭成员的信息：

文件：people/family/wife.md 中提到，"我的妻子叫王秀英，我们结婚50年了。"

文件：people/family/children.md 中提到，"我有两个孩子，他们都很孝顺。"

总结：您的家庭成员包括妻子王秀英和两个孩子。
"""
        
        result = querier._parse_final_answer(natural_output)
        logger.info(f"解析结果: {result}")
        
        # 验证解析结果
        assert "related_memories" in result, "Should have related_memories"
        assert len(result["related_memories"]) == 1, "Should have 1 memory in fallback mode"
        assert result["related_memories"][0]["source"] == "people/family/wife.md", "Should extract correct source"
        assert "王秀英" in result["related_memories"][0]["content"], "Should contain wife's name"
        assert "两个孩子" in result["related_memories"][0]["content"], "Should contain children information"
        assert result["related_memories"][0].get("confidence") == 0.8, "Should have confidence score"
        assert result["related_memories"][0].get("extraction_method") == "natural_language_fallback", "Should have extraction method"
        
        logger.info("✅ 自然语言描述解析测试通过")
        
        # 清理测试环境
        import shutil
        shutil.rmtree(temp_dir)
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_parse_mixed_format():
    """测试解析混合格式输出"""
    logger.info("\n=== 测试3：解析混合格式输出 ===")
    
    try:
        querier, temp_dir = await setup_test_environment()
        
        # 混合格式输出
        mixed_output = """
我已经找到了相关信息：

Final Answer:
{
  "query_intent": "查询家庭成员信息",
  "related_memories": [
    {
      "source": "people/family/wife.md",
      "content": "我的妻子叫王秀英，我们结婚50年了。",
      "relevance": "直接相关",
      "memory_type": "long_term"
    }
  ],
  "linked_context": [],
  "search_summary": "找到了1个相关文件"
}

另外，在people/family/children.md中还提到您有两个孩子。
"""
        
        result = querier._parse_final_answer(mixed_output)
        logger.info(f"解析结果: {result}")
        
        # 验证解析结果（应该优先解析JSON部分）
        assert "related_memories" in result, "Should have related_memories"
        assert len(result["related_memories"]) == 1, "Should have 1 memory from JSON"
        assert result["related_memories"][0]["source"] == "people/family/wife.md", "Should have correct source from JSON"
        
        logger.info("✅ 混合格式解析测试通过")
        
        # 清理测试环境
        import shutil
        shutil.rmtree(temp_dir)
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_parse_unparseable():
    """测试解析完全无法解析的输出"""
    logger.info("\n=== 测试4：解析完全无法解析的输出 ===")
    
    try:
        querier, temp_dir = await setup_test_environment()
        
        # 完全无法解析的输出
        unparseable_output = """
抱歉，我无法找到您的家庭成员信息。请尝试更具体的查询。
"""
        
        result = querier._parse_final_answer(unparseable_output)
        logger.info(f"解析结果: {result}")
        
        # 验证解析结果（应该返回自然语言降级结构）
        assert "related_memories" in result, "Should have related_memories"
        assert len(result["related_memories"]) == 1, "Should have 1 memory in fallback mode"
        assert result["related_memories"][0]["source"] == "unknown", "Should have unknown source"
        assert "抱歉，我无法找到您的家庭成员信息" in result["related_memories"][0]["content"], "Should contain original content"
        assert result["related_memories"][0].get("extraction_method") == "natural_language_fallback", "Should have extraction method"
        
        logger.info("✅ 无法解析输出的降级处理测试通过")
        
        # 清理测试环境
        import shutil
        shutil.rmtree(temp_dir)
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行所有测试"""
    logger.info("开始测试_parse_final_answer方法的兼容性适配")
    
    # 运行测试
    tests = [
        test_parse_json_format,
        test_parse_natural_language,
        test_parse_mixed_format,
        test_parse_unparseable
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
    import asyncio
    asyncio.run(main())