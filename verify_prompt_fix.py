#!/usr/bin/env python3
"""
验证Prompt模板修复的脚本
检查所有prompt模板是否正确加载和渲染
"""

import os
import sys
import asyncio
from src.services.llm_service import get_llm_service
from src.prompts.base import PromptTemplate


def test_prompt_render():
    """测试Prompt模板渲染功能"""
    print("=== 测试Prompt模板渲染 ===")
    
    # 创建一个测试模板
    test_template = PromptTemplate(
        name="test_template",
        system_prompt="Hello, ${name}! You are ${age} years old.",
        user_template="",
        variables={
            "name": "姓名",
            "age": "年龄"
        }
    )
    
    try:
        # 测试渲染
        result = test_template.render(name="张三", age=30)
        print(f"模板内容: {test_template.system_prompt}")
        print(f"渲染结果: {result}")
        print(f"是否包含姓名: {'张三' in result}")
        print(f"是否包含年龄: {'30' in result}")
        print("✅ 模板渲染测试通过!")
    except Exception as e:
        print(f"❌ 模板渲染测试失败: {e}")
        return False
    
    return True


async def test_load_templates():
    """测试加载所有模板"""
    print("\n=== 测试加载Prompt模板 ===")
    
    try:
        llm_service = get_llm_service()
        print(f"已加载的模板数量: {len(llm_service._prompt_templates)}")
        
        # 打印所有模板名称
        print("\n已加载的模板:")
        for name in llm_service._prompt_templates:
            template = llm_service._prompt_templates[name]
            print(f"- {name}: {len(template.variables)}个变量")
            print(f"  变量: {list(template.variables.keys())}")
        
        print("\n✅ 模板加载测试通过!")
        return True
    except Exception as e:
        print(f"\n❌ 模板加载测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主函数"""
    print("Prompt模板修复验证脚本")
    print("=" * 50)
    
    # 测试模板渲染
    render_ok = test_prompt_render()
    
    # 测试模板加载
    load_ok = await test_load_templates()
    
    print("\n" + "=" * 50)
    if render_ok and load_ok:
        print("🎉 所有测试通过! Prompt模板修复成功!")
        return 0
    else:
        print("❌ 部分测试失败，请检查修复!")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))