# src/services/question_generator.py
from typing import List, Optional
import logging

from src.services.llm_service import LLMService, get_llm_service
from src.models import EmotionResult, MemoryQueryResult, SessionState
from src.enums import PhaseType

logger = logging.getLogger(__name__)


class QuestionGenerator:
    """
    问题生成服务
    
    职责：
    - 根据当前状态生成下一个对话问题
    - 处理情绪响应
    - 管理问题优先级
    
    使用场景：
    - ConversationOrchestrator 每轮调用
    
    调用LLMService：
    - 使用 "question_generation" 模板生成问题
    - 使用 "emotion_response" 模板生成情绪响应
    """
    
    def __init__(self, llm_service: LLMService = None):
        """
        初始化
        
        Args:
            llm_service: LLM服务实例
        """
        self.llm_service = llm_service or get_llm_service()
    
    async def generate(
        self,
        user_input: str,
        emotion: EmotionResult,
        memory: MemoryQueryResult,
        state: SessionState,
    ) -> str:
        """
        生成下一个问题
        
        Args:
            user_input: 用户输入
            emotion: 情绪结果
            memory: 记忆查询结果
            state: 会话状态
            
        Returns:
            下一个问题文本
        """
        # 优先级决策链
        
        # 1. 情绪响应优先
        if emotion.needs_special_handling:
            return await self._generate_emotion_response(user_input, emotion)
        
        # 2. 待追问问题
        if state.has_pending_questions():
            return state.pop_pending_question()
        
        # 3. 阶段切换
        if self._should_change_phase(state):
            return self._get_phase_transition_question(state)
        
        # 4. 基于上下文生成
        return await self._generate_contextual_question(user_input, memory, state)
    
    async def _generate_emotion_response(
        self,
        user_input: str,
        emotion: EmotionResult,
    ) -> str:
        """生成情绪响应"""
        result = await self.llm_service.invoke_with_template(
            template_name="emotion_response",
            variables={
                "user_input": user_input,
                "emotion_type": emotion.emotion_type,
                "emotion_intensity": emotion.intensity,
                "suggested_action": emotion.suggested_action,
            },
        )
        
        if result.success:
            return result.content
        else:
            # 降级：使用预设响应
            return self._get_fallback_emotion_response(emotion)
    
    def _get_fallback_emotion_response(self, emotion: EmotionResult) -> str:
        """获取降级情绪响应"""
        responses = {
            "sadness_high": "我理解这段回忆对您来说有些沉重，我们可以先停一停。",
            "fatigue": "我们今天聊了不少了，您要不要休息一下？",
            "reluctance": "这个话题如果让您不舒服，我们换一个聊聊？",
        }
        key = f"{emotion.emotion_type}_{emotion.intensity}"
        return responses.get(key, "我理解您的感受，您想继续聊聊还是换个话题？")
    
    async def _generate_contextual_question(
        self,
        user_input: str,
        memory: MemoryQueryResult,
        state: SessionState,
    ) -> str:
        """基于上下文生成问题"""
        # 格式化记忆内容
        memory_str = self._format_memory(memory)
        
        # 调用LLM
        result = await self.llm_service.invoke_with_template(
            template_name="question_generation",
            variables={
                "strategy": state.strategy,
                "current_phase": state.current_phase,
                "turn_count": state.turn_count,
                "coverage": str(state.coverage),
                "user_input": user_input,
                "related_memory": memory_str,
                "pending_questions": str(state.pending_questions[:3]) if state.pending_questions else "无",
                "emotion_type": "neutral",
                "emotion_intensity": "low",
            },
        )
        
        if result.success:
            return result.content.strip()
        else:
            # 降级：使用默认问题
            return self._get_default_question(state.current_phase)
    
    def _format_memory(self, memory: MemoryQueryResult) -> str:
        """格式化记忆内容"""
        if not memory.has_results:
            return "（无相关记忆）"
        
        lines = []
        for entry in memory.get_top_entries(3):
            lines.append(f"- [{entry.memory_type}] {entry.content[:100]}")
        
        return "\n".join(lines)
    
    def _should_change_phase(self, state: SessionState) -> bool:
        """判断是否应该切换阶段"""
        current_coverage = state.coverage.get(state.current_phase, 0)
        
        # 当前阶段覆盖率超过80%，且还有后续阶段
        if current_coverage >= 0.8:
            phase_order = [
                PhaseType.CHILDHOOD,
                PhaseType.YOUTH,
                PhaseType.YOUNG_ADULT,
                PhaseType.MIDDLE_AGE,
                PhaseType.ELDERLY,
            ]
            current_idx = phase_order.index(state.current_phase)
            return current_idx < len(phase_order) - 1
        
        return False
    
    def _get_phase_transition_question(self, state: SessionState) -> str:
        """获取阶段过渡问题"""
        transitions = {
            (PhaseType.CHILDHOOD, PhaseType.YOUTH): 
                "童年时光聊得差不多了，我们来聊聊您的学生时代吧？那时候有什么难忘的经历？",
            (PhaseType.YOUTH, PhaseType.YOUNG_ADULT):
                "学生时代聊完了，接下来我们聊聊您刚工作的那几年？第一份工作是什么样的？",
            (PhaseType.YOUNG_ADULT, PhaseType.MIDDLE_AGE):
                "青年时期聊得差不多了，我们来聊聊您事业发展的黄金时期？那时候有什么成就？",
            (PhaseType.MIDDLE_AGE, PhaseType.ELDERLY):
                "中年奋斗的岁月聊完了，我们来聊聊您退休后的生活？现在每天最期待什么？",
        }
        
        # 确定下一个阶段
        phase_order = list(PhaseType)
        current_idx = phase_order.index(state.current_phase)
        next_phase = phase_order[current_idx + 1] if current_idx + 1 < len(phase_order) else None
        
        if next_phase:
            return transitions.get(
                (state.current_phase, next_phase),
                f"我们来聊聊下一个阶段的生活吧？"
            )
        
        return "您的人生经历很丰富，还有什么想分享的吗？"
    
    def _get_default_question(self, phase: PhaseType) -> str:
        """获取默认问题"""
        defaults = {
            PhaseType.CHILDHOOD: "您最早的记忆是什么？",
            PhaseType.YOUTH: "学生时代最难忘的事是什么？",
            PhaseType.YOUNG_ADULT: "您是如何开始第一份工作的？",
            PhaseType.MIDDLE_AGE: "事业上最大的成就是什么？",
            PhaseType.ELDERLY: "退休后的生活和想象中一样吗？",
        }
        return defaults.get(phase, "能讲讲您的经历吗？")