#!/usr/bin/env python3
"""
验证LLMService的基本功能
"""

import sys
import os
import asyncio
import logging
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    print("=== 验证LLMService功能 ===")
    
    # 测试LLMConfig
    print("\n1. 测试LLMConfig配置")
    try:
        from src.config.llm_config import LLMConfig
        
        # 创建配置对象
        config = LLMConfig(
            provider="openai",
            model_name="gpt-4o",
            api_key="test-key",
            temperature=0.5,
            max_tokens=1024
        )
        
        print(f"✅ LLMConfig创建成功")
        print(f"   Provider: {config.provider}")
        print(f"   Model: {config.model_name}")
        print(f"   Temperature: {config.temperature}")
        print(f"   Max Tokens: {config.max_tokens}")
        
    except Exception as e:
        print(f"❌ LLMConfig测试失败: {e}")
        return 1
    
    # 测试PromptTemplate
    print("\n2. 测试PromptTemplate")
    try:
        from src.prompts.base import PromptTemplate
        
        # 创建简单模板
        template = PromptTemplate(
            name="test_template",
            description="测试模板",
            system_prompt="你是一个测试助手",
            user_template="请回答：{question}",
            variables={"question": "要问的问题"}
        )
        
        # 渲染模板
        rendered = template.render(question="什么是AI？")
        print(f"✅ PromptTemplate创建成功")
        print(f"   渲染结果: {rendered}")
        
        # 验证变量
        valid = template.validate_variables(question="测试问题")
        print(f"   变量验证: {'通过' if valid else '失败'}")
        
    except Exception as e:
        print(f"❌ PromptTemplate测试失败: {e}")
        return 1
    
    # 测试加载模板
    print("\n3. 测试加载所有Prompt模板")
    try:
        from src.prompts import TEMPLATES
        
        print(f"✅ 成功加载 {len(TEMPLATES)} 个模板")
        for name in TEMPLATES.keys():
            print(f"   - {name}")
        
    except Exception as e:
        print(f"❌ 模板加载失败: {e}")
        return 1
    
    # 测试LLMService初始化（模拟）
    print("\n4. 测试LLMService初始化")
    try:
        from src.services.llm_service import LLMService
        
        # 模拟模型初始化，避免实际调用API
        with open(os.devnull, 'w') as f, redirect_stdout(f), redirect_stderr(f):
            # 使用mock来避免实际调用
            from unittest.mock import patch
            
            with patch("src.services.llm_service.ChatOpenAI") as mock_openai:
                mock_instance = MagicMock()
                mock_openai.return_value = mock_instance
                
                llm_service = LLMService(config)
                llm_service._model = mock_instance
        
        print(f"✅ LLMService初始化成功")
        print(f"   已加载 {len(llm_service._prompt_templates)} 个模板")
        
    except Exception as e:
        print(f"❌ LLMService初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print("\n=== 所有验证完成 ===")
    print("🎉 LLMService实现成功！")
    return 0

if __name__ == "__main__":
    # 导入所需的辅助类
    from unittest.mock import MagicMock
    from contextlib import redirect_stdout, redirect_stderr
    
    sys.exit(asyncio.run(main()))