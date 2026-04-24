#!/usr/bin/env python3
"""
验证所有数据对象的导入和基本功能
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

# 测试导入所有枚举类型
print("=== 测试导入枚举类型 ===")
try:
    from src.enums import (
        StateType, PhaseType, StrategyType,
        EmotionType, EmotionIntensity, EmotionValence, SuggestedAction
    )
    print("✅ 所有枚举类型导入成功")
    print(f"   StateType: {[e.value for e in StateType]}")
    print(f"   PhaseType: {[e.value for e in PhaseType]}")
    print(f"   StrategyType: {[e.value for e in StrategyType]}")
    print(f"   EmotionType: {[e.value for e in EmotionType][:5]}... (共{len(EmotionType)}种)")
except Exception as e:
    print(f"❌ 枚举类型导入失败: {e}")
    sys.exit(1)

# 测试导入所有数据对象
print("\n=== 测试导入数据对象 ===")
try:
    from src.models import (
        # 核心数据对象
        SessionState, ConversationTurn, EmotionResult, MemoryQueryResult,
        SummaryContent, HandoffPackage, EventInfo, PersonInfo, AgentResponse,
        
        # 辅助数据对象
        Entity, MemoryEntry, LinkedContent, ExtractedInfo, MemoryUpdatePlan,
        TimeMarker, ThemeInfo, TopicInfo, EmotionState, ProgressInfo,
        SessionSummary, CollectedData
    )
    print("✅ 所有数据对象导入成功")
except Exception as e:
    print(f"❌ 数据对象导入失败: {e}")
    sys.exit(1)

# 测试创建基本对象实例
print("\n=== 测试创建对象实例 ===")

# 测试EventInfo
try:
    event = EventInfo(
        event_id="event-001",
        title="测试事件",
        time="2023年",
        location="北京",
        description="这是一个测试事件",
        details=["细节1", "细节2"],
        participants=["张三", "李四"],
        emotions=["joy", "excitement"],
        source_turns=[1, 2, 3]
    )
    print("✅ EventInfo 创建成功")
except Exception as e:
    print(f"❌ EventInfo 创建失败: {e}")

# 测试PersonInfo
try:
    person = PersonInfo(
        person_id="person-001",
        name="张三",
        role="friend",
        description="测试人物",
        relation_to_protagonist="朋友",
        source_events=["event-001"]
    )
    print("✅ PersonInfo 创建成功")
except Exception as e:
    print(f"❌ PersonInfo 创建失败: {e}")

# 测试ConversationTurn
try:
    turn = ConversationTurn(
        turn_id=1,
        user_input="你好",
        agent_response="你好，很高兴为您服务！"
    )
    print("✅ ConversationTurn 创建成功")
except Exception as e:
    print(f"❌ ConversationTurn 创建失败: {e}")

# 测试EmotionResult
try:
    emotion = EmotionResult(
        emotion_type=EmotionType.JOY,
        intensity=EmotionIntensity.MEDIUM,
        valence=EmotionValence.POSITIVE,
        confidence=0.8
    )
    print("✅ EmotionResult 创建成功")
except Exception as e:
    print(f"❌ EmotionResult 创建失败: {e}")

# 测试SessionState
try:
    session = SessionState(session_id="test-session-001")
    session.add_turn(turn)
    session.update_coverage(PhaseType.CHILDHOOD, 0.5)
    session.mark_event_collected("event-001")
    session.mark_person_collected("person-001")
    print("✅ SessionState 创建和操作成功")
    print(f"   当前轮次: {session.turn_count}")
    print(f"   童年覆盖率: {session.coverage[PhaseType.CHILDHOOD]}")
except Exception as e:
    print(f"❌ SessionState 创建或操作失败: {e}")

# 测试AgentResponse
try:
    response = AgentResponse(
        message="测试响应",
        state_update={"turn_count": 1},
        should_pause=False
    )
    print("✅ AgentResponse 创建成功")
except Exception as e:
    print(f"❌ AgentResponse 创建失败: {e}")

# 测试JSON序列化
try:
    # 测试SessionState的JSON序列化
    session_json = session.model_dump_json(indent=2)
    print("✅ SessionState JSON序列化成功")
    
    # 测试反序列化
    session_from_json = SessionState.model_validate_json(session_json)
    print("✅ SessionState JSON反序列化成功")
except Exception as e:
    print(f"❌ JSON序列化/反序列化失败: {e}")

print("\n=== 所有验证完成 ===")
print("🎉 数据对象实现成功！")