#!/usr/bin/env python3
"""
核心服务验证脚本
验证 EmotionDetector、KnowledgeBaseQuerier 和 QuestionGenerator 的基本结构是否正确
不依赖LLM调用，只测试实例化和基础功能
"""

import os
import logging
from pathlib import Path

# 设置日志级别
logging.basicConfig(level=logging.INFO)

# 添加项目根目录到路径
import sys
sys.path.append(str(Path(__file__).parent))

from src.models import SessionState, EmotionResult, MemoryQueryResult, ConversationTurn
from src.enums import PhaseType, StrategyType, StateType

# 验证EmotionDetector的结构
try:
    from src.services.emotion_detector import EmotionDetector
    print("✅ EmotionDetector 导入成功")
    
    # 检查类方法
    methods = [method for method in dir(EmotionDetector) if not method.startswith("_")]
    required_methods = ["detect", "get_response_strategy"]
    for method in required_methods:
        if method in methods:
            print(f"   ✅ EmotionDetector.{method}() 方法存在")
        else:
            print(f"   ❌ EmotionDetector.{method}() 方法缺失")
    
except Exception as e:
    print(f"❌ EmotionDetector 导入失败: {e}")

# 验证KnowledgeBaseQuerier的结构
try:
    from src.services.knowledge_base_querier import KnowledgeBaseQuerier, KnowledgeBaseTools
    from src.storage.markdown_file_manager import MarkdownFileManager
    
    print("\n✅ KnowledgeBaseQuerier 导入成功")
    
    # 检查类方法
    methods = [method for method in dir(KnowledgeBaseQuerier) if not method.startswith("_")]
    required_methods = ["query"]
    for method in required_methods:
        if method in methods:
            print(f"   ✅ KnowledgeBaseQuerier.{method}() 方法存在")
        else:
            print(f"   ❌ KnowledgeBaseQuerier.{method}() 方法缺失")
    
    # 测试KnowledgeBaseTools类
    print("   ✅ KnowledgeBaseTools 类存在")
    
    # 测试文件管理器实例化（这不会调用LLM）
    file_manager = MarkdownFileManager()
    print("   ✅ MarkdownFileManager 实例化成功")
    
    # 创建工具集
    tools = KnowledgeBaseTools(file_manager)
    print("   ✅ KnowledgeBaseTools 实例化成功")
    print(f"   ✅ 工具集包含 {len(tools.tools)} 个工具")
    
    # 显示工具信息
    for i, t in enumerate(tools.tools):
        print(f"      - 工具 {i+1}: {type(t).__name__}")
        
except Exception as e:
    print(f"❌ KnowledgeBaseQuerier 导入或测试失败: {e}")
    import traceback
    traceback.print_exc()

# 验证QuestionGenerator的结构
try:
    from src.services.question_generator import QuestionGenerator
    print("\n✅ QuestionGenerator 导入成功")
    
    # 检查类方法
    methods = [method for method in dir(QuestionGenerator) if not method.startswith("_")]
    required_methods = ["generate", "_generate_emotion_response", "_generate_contextual_question"]
    for method in required_methods:
        if method in methods:
            print(f"   ✅ QuestionGenerator.{method}() 方法存在")
        else:
            print(f"   ❌ QuestionGenerator.{method}() 方法缺失")
    
    # 测试一些辅助方法
    test_state = SessionState(
        session_id="test_session",
        current_state=StateType.COLLECT,
        current_phase=PhaseType.CHILDHOOD,
        strategy=StrategyType.TIMELINE_CLASSIC,
        turn_count=1,
        coverage={PhaseType.CHILDHOOD: 0.2}
    )
    
    # 实例化并测试辅助方法（不调用LLM）
    # 注意：不调用__init__因为它会尝试获取LLM服务
    qg = QuestionGenerator.__new__(QuestionGenerator)
    
    # 测试_should_change_phase方法
    result = qg._should_change_phase(test_state)
    print(f"   ✅ QuestionGenerator._should_change_phase() 测试通过: {result}")
    
    # 测试_get_default_question方法
    question = qg._get_default_question(PhaseType.CHILDHOOD)
    print(f"   ✅ QuestionGenerator._get_default_question() 测试通过: {question}")
    
    # 测试_get_fallback_emotion_response方法
    emotion = EmotionResult.default_neutral()
    fallback_response = qg._get_fallback_emotion_response(emotion)
    print(f"   ✅ QuestionGenerator._get_fallback_emotion_response() 测试通过: {fallback_response}")
    
except Exception as e:
    print(f"❌ QuestionGenerator 导入或测试失败: {e}")
    import traceback
    traceback.print_exc()

# 验证模型和枚举的导入
try:
    from src.models import (
        EmotionResult,
        MemoryQueryResult,
        MemoryEntry,
        LinkedContent,
        SessionState,
        ConversationTurn
    )
    from src.enums import (
        EmotionType,
        EmotionIntensity,
        EmotionValence,
        SuggestedAction,
        PhaseType,
        StrategyType,
        StateType
    )
    
    print("\n✅ 所有模型和枚举导入成功")
    
    # 测试模型实例化
    emotion = EmotionResult.default_neutral()
    memory = MemoryQueryResult.empty()
    entry = MemoryEntry(source="test.md", content="test content", relevance=0.8, memory_type="long_term")
    linked = LinkedContent(source="source.md", target="target.md", relation="related")
    
    print("   ✅ 模型实例化测试通过")
    
except Exception as e:
    print(f"❌ 模型或枚举导入失败: {e}")

# 验证配置文件
try:
    from src.config.llm_config import LLMConfig
    print("\n✅ 配置文件导入成功")
    print("   ✅ LLMConfig 类存在")
except Exception as e:
    print(f"❌ 配置文件导入失败: {e}")

# 验证Prompt模板导入
try:
    from src.prompts.base import PromptTemplate
    print("\n✅ Prompt模板导入成功")
    print("   ✅ PromptTemplate 类存在")
except Exception as e:
    print(f"❌ Prompt模板导入失败: {e}")

print("\n" + "=" * 50)
print("🎉 核心服务结构验证完成!")
print("注意：完整功能测试需要配置Qwen API密钥")