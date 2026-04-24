# src/services/emotion_detector.py
from typing import List
import logging

from src.services.llm_service import LLMService, get_llm_service
from src.models import EmotionResult, ConversationTurn
from src.enums import EmotionType, EmotionIntensity, EmotionValence, SuggestedAction

logger = logging.getLogger(__name__)


class EmotionDetector:
    """
    情绪识别服务
    
    职责：
    - 识别用户输入的情绪状态
    - 判断是否需要特殊处理
    - 提供响应策略建议
    
    使用场景：
    - ConversationOrchestrator 每轮调用
    - QuestionGenerator 生成情绪响应时参考
    
    调用LLMService：
    - 使用 "emotion_detection" 模板
    - 结构化输出 EmotionResult
    """
    
    def __init__(self, llm_service: LLMService = None):
        """
        初始化
        
        Args:
            llm_service: LLM服务实例（可选，默认使用全局实例）
        """
        self.llm_service = llm_service or get_llm_service()
    
    async def detect(
        self,
        user_input: str,
        conversation_history: List[ConversationTurn],
    ) -> EmotionResult:
        """
        识别情绪
        
        Args:
            user_input: 用户输入文本
            conversation_history: 对话历史
            
        Returns:
            EmotionResult: 情绪识别结果
        """
        # 格式化对话历史
        history_str = self._format_history(conversation_history)
        
        # 调用LLMService
        result, raw = await self.llm_service.invoke_structured(
            template_name="emotion_detection",
            variables={
                "user_input": user_input,
                "conversation_history": history_str,
            },
            output_model=EmotionResult,
        )
        
        # 降级处理
        if result is None:
            logger.warning(f"Emotion detection failed, using default: {raw.error}")
            return EmotionResult.default_neutral()
        
        logger.info(f"Emotion detected: {result.emotion_type} ({result.intensity})")
        return result
    
    def _format_history(self, history: List[ConversationTurn], n: int = 3) -> str:
        """格式化对话历史"""
        recent = history[-n:] if history else []
        lines = []
        for turn in recent:
            lines.append(f"用户：{turn.user_input}")
            if turn.agent_response:
                lines.append(f"助手：{turn.agent_response}")
        return "\n".join(lines) if lines else "（无历史对话）"
    
    def get_response_strategy(self, emotion: EmotionResult) -> dict:
        """
        获取响应策略
        
        Args:
            emotion: 情绪结果
            
        Returns:
            响应策略配置
        """
        strategies = {
            # 高强度负面情绪 → 暂停+安慰
            "negative_high": {
                "action": "pause",
                "tone": "empathetic",
                "suggest_break": True,
            },
            # 中等强度负面情绪 → 安慰+换话题
            "negative_medium": {
                "action": "comfort",
                "tone": "gentle",
                "suggest_redirect": True,
            },
            # 疲劳 → 建议休息
            "fatigue": {
                "action": "pause",
                "tone": "caring",
                "suggest_break": True,
            },
            # 正向情绪 → 继续深入
            "positive": {
                "action": "continue",
                "tone": "encouraging",
                "deepen": True,
            },
            # 默认
            "default": {
                "action": "continue",
                "tone": "neutral",
            },
        }
        
        key = f"{emotion.valence}_{emotion.intensity}"
        if emotion.emotion_type == EmotionType.FATIGUE:
            key = "fatigue"
        
        return strategies.get(key, strategies["default"])