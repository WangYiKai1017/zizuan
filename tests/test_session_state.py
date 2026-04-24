import pytest
from datetime import datetime
from src.models import SessionState, ConversationTurn
from src.enums import StateType, PhaseType, StrategyType, EmotionType


class TestSessionState:
    def test_create_session(self):
        """测试创建会话"""
        session = SessionState(session_id="test-001")
        assert session.session_id == "test-001"
        assert session.current_state == StateType.INIT
        assert session.current_phase == PhaseType.CHILDHOOD
        assert session.strategy == StrategyType.SPARKLE_FIRST
        assert session.turn_count == 0
        assert len(session.conversation_history) == 0
    
    def test_add_turn(self):
        """测试添加对话轮次"""
        session = SessionState(session_id="test-001")
        turn = ConversationTurn(turn_id=1, user_input="测试输入")
        session.add_turn(turn)
        
        assert session.turn_count == 1
        assert len(session.conversation_history) == 1
        assert session.conversation_history[0].turn_id == 1
        assert session.conversation_history[0].user_input == "测试输入"
    
    def test_update_coverage(self):
        """测试更新覆盖率"""
        session = SessionState(session_id="test-001")
        session.update_coverage(PhaseType.CHILDHOOD, 0.5)
        
        assert session.coverage[PhaseType.CHILDHOOD] == 0.5
        
        # 测试边界值
        session.update_coverage(PhaseType.CHILDHOOD, 1.5)
        assert session.coverage[PhaseType.CHILDHOOD] == 1.0
        
        session.update_coverage(PhaseType.CHILDHOOD, -0.5)
        assert session.coverage[PhaseType.CHILDHOOD] == 0.0
    
    def test_collect_events_people(self):
        """测试标记事件和人物已采集"""
        session = SessionState(session_id="test-001")
        
        session.mark_event_collected("event-001")
        session.mark_event_collected("event-002")
        session.mark_person_collected("person-001")
        
        assert len(session.collected_events) == 2
        assert "event-001" in session.collected_events
        assert "event-002" in session.collected_events
        assert len(session.collected_people) == 1
        assert "person-001" in session.collected_people
        
        # 测试重复添加
        session.mark_event_collected("event-001")
        assert len(session.collected_events) == 2
    
    def test_pending_questions(self):
        """测试待追问问题"""
        session = SessionState(session_id="test-001")
        
        # 测试添加问题
        session.push_pending_question("问题1")
        session.push_pending_question("问题2")
        
        assert session.has_pending_questions()
        assert len(session.pending_questions) == 2
        
        # 测试获取问题
        question1 = session.pop_pending_question()
        question2 = session.pop_pending_question()
        
        assert question1 == "问题1"
        assert question2 == "问题2"
        assert not session.has_pending_questions()
        
        # 测试空列表获取
        assert session.pop_pending_question() is None
    
    def test_to_summary(self):
        """测试生成摘要"""
        session = SessionState(session_id="test-001")
        summary = session.to_summary()
        
        assert "session_id" in summary
        assert "current_state" in summary
        assert "current_phase" in summary
        assert "turn_count" in summary
        assert "coverage" in summary
        assert "collected_events_count" in summary
        assert "collected_people_count" in summary
        
        assert summary["session_id"] == "test-001"
        assert summary["turn_count"] == 0
    
    def test_get_recent_history(self):
        """测试获取最近对话"""
        session = SessionState(session_id="test-001")
        
        # 添加3轮对话
        for i in range(3):
            turn = ConversationTurn(turn_id=i+1, user_input=f"输入{i+1}")
            session.add_turn(turn)
        
        # 获取最近2轮
        recent = session.get_recent_history(n=2)
        assert len(recent) == 2
        assert recent[0].turn_id == 2
        assert recent[1].turn_id == 3
        
        # 获取最近10轮（超过实际轮数）
        recent = session.get_recent_history(n=10)
        assert len(recent) == 3
    
    def test_update_from_emotion(self):
        """测试从情绪结果更新状态"""
        from src.models import EmotionResult
        from src.enums import EmotionIntensity, EmotionValence, SuggestedAction
        
        session = SessionState(session_id="test-001")
        emotion_result = EmotionResult(
            emotion_type=EmotionType.JOY,
            intensity=EmotionIntensity.MEDIUM,
            valence=EmotionValence.POSITIVE,
            confidence=0.8,
            suggested_action=SuggestedAction.CONTINUE
        )
        
        session.update_from_emotion(emotion_result)
        
        assert session.emotion_state.emotion_type == EmotionType.JOY
        assert session.emotion_state.intensity == EmotionIntensity.MEDIUM
        assert session.emotion_state.last_change_turn == 0
        
        # 添加一轮对话后再更新情绪
        turn = ConversationTurn(turn_id=1, user_input="测试输入")
        session.add_turn(turn)
        session.update_from_emotion(emotion_result)
        
        assert session.emotion_state.last_change_turn == 1