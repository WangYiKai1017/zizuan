#!/usr/bin/env python3
"""
核心服务测试脚本
测试 EmotionDetector、KnowledgeBaseQuerier 和 QuestionGenerator 的基本功能
"""

import asyncio
import os
import logging
from pathlib import Path

# 设置日志级别
logging.basicConfig(level=logging.INFO)

# 添加项目根目录到路径
import sys
sys.path.append(str(Path(__file__).parent))

from src.services.emotion_detector import EmotionDetector
from src.services.knowledge_base_querier import KnowledgeBaseQuerier
from src.services.question_generator import QuestionGenerator
from src.storage.markdown_file_manager import MarkdownFileManager
from src.models import SessionState, EmotionResult, MemoryQueryResult, ConversationTurn
from src.enums import PhaseType, StrategyType, StateType


async def test_emotion_detector():
    """测试情绪识别服务"""
    print("\n=== 测试 EmotionDetector ===")
    
    try:
        emotion_detector = EmotionDetector()
        
        # 测试正面情绪
        positive_input = "我小时候最开心的事就是和小伙伴们一起去河边钓鱼，那时候的天空特别蓝。"
        history = [
            ConversationTurn(turn_id=1, user_input="你好，我想聊聊我的童年", agent_response="好的，我很乐意听您分享。")
        ]
        
        positive_result = await emotion_detector.detect(positive_input, history)
        print(f"正面情绪测试结果: {positive_result.emotion_type} ({positive_result.intensity})")
        print(f"   Valence: {positive_result.valence}")
        print(f"   Action: {positive_result.suggested_action}")
        
        # 测试负面情绪
        negative_input = "说起那段时间，我总是忍不住难过，那是我人生中最黑暗的时刻。"
        negative_result = await emotion_detector.detect(negative_input, history)
        print(f"负面情绪测试结果: {negative_result.emotion_type} ({negative_result.intensity})")
        print(f"   Valence: {negative_result.valence}")
        print(f"   Action: {negative_result.suggested_action}")
        
        return True
        
    except Exception as e:
        print(f"EmotionDetector 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_knowledge_base_querier():
    """测试知识库查询服务"""
    print("\n=== 测试 KnowledgeBaseQuerier ===")
    
    try:
        # 创建一个临时的文件管理器
        file_manager = MarkdownFileManager()
        querier = KnowledgeBaseQuerier(file_manager)
        
        # 创建一个简单的会话状态
        session_state = SessionState(
            session_id="test_session",
            current_state=StateType.COLLECT,
            current_phase=PhaseType.CHILDHOOD,
            strategy=StrategyType.TIMELINE_CLASSIC,
            turn_count=1,
            coverage={PhaseType.CHILDHOOD: 0.2}
        )
        
        # 测试查询
        user_input = "我想了解童年时期的事情"
        result = await querier.query(user_input, session_state, target_path="C:\\Users\\MSI\\AppData\\Local\\Temp\\memory\\3332221e")
        
        print(f"查询结果: {result.query}")
        print(f"相关记忆数量: {result.total_count}")
        
        if result.has_results:
            for entry in result.entries[:2]:
                print(f"   - {entry.source}: {entry.content[:100]}...")
        else:
            print("   没有找到相关记忆")
        
        return True
        
    except Exception as e:
        print(f"KnowledgeBaseQuerier 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_question_generator():
    """测试问题生成服务"""
    print("\n=== 测试 QuestionGenerator ===")
    
    try:
        question_generator = QuestionGenerator()
        
        # 创建测试数据
        user_input = "我小时候住在一个小山村，那里的风景特别美。"
        emotion = EmotionResult.default_neutral()
        memory = MemoryQueryResult.empty()
        session_state = SessionState(
            session_id="test_session",
            current_state=StateType.COLLECT,
            current_phase=PhaseType.CHILDHOOD,
            strategy=StrategyType.TIMELINE_CLASSIC,
            turn_count=2,
            coverage={PhaseType.CHILDHOOD: 0.3}
        )
        
        # 生成问题
        question = await question_generator.generate(user_input, emotion, memory, session_state)
        print(f"生成的问题: {question}")
        
        # 测试阶段切换逻辑
        print("\n测试阶段切换逻辑:")
        session_state.coverage[PhaseType.CHILDHOOD] = 0.9
        if question_generator._should_change_phase(session_state):
            transition_question = question_generator._get_phase_transition_question(session_state)
            print(f"阶段切换问题: {transition_question}")
        else:
            print("不需要切换阶段")
        
        return True
        
    except Exception as e:
        print(f"QuestionGenerator 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print("核心服务测试脚本")
    print("=" * 50)
    
    # 测试各个服务
    emotion_ok = await test_emotion_detector()
    querier_ok = await test_knowledge_base_querier()
    question_ok = await test_question_generator()
    
    print("\n" + "=" * 50)
    if emotion_ok and querier_ok and question_ok:
        print("🎉 所有核心服务测试通过!")
        return 0
    else:
        print("❌ 部分核心服务测试失败!")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))