from pydantic import BaseModel, Field
from typing import Optional
from src.enums import EmotionType, EmotionIntensity, EmotionValence, SuggestedAction


class EmotionResult(BaseModel):
    """
    情绪识别结果
    
    职责：
    - 记录情绪识别的完整结果
    - 提供响应建议
    
    使用场景：
    - EmotionDetector.detect() 的返回值
    - ConversationOrchestrator 根据情绪调整策略
    - QuestionGenerator 根据情绪生成响应
    """
    
    emotion_type: EmotionType = Field(..., description="情绪类型")
    intensity: EmotionIntensity = Field(default=EmotionIntensity.LOW, description="情绪强度")
    valence: EmotionValence = Field(default=EmotionValence.NEUTRAL, description="情绪极性")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")
    suggested_action: SuggestedAction = Field(
        default=SuggestedAction.CONTINUE,
        description="建议动作"
    )
    
    @property
    def needs_special_handling(self) -> bool:
        """是否需要特殊处理"""
        return (
            self.intensity == EmotionIntensity.HIGH and 
            self.valence == EmotionValence.NEGATIVE
        ) or self.emotion_type in [
            EmotionType.FATIGUE,
            EmotionType.RELUCTANCE,
            EmotionType.CONFUSION
        ]
    
    def should_pause(self) -> bool:
        """是否应该暂停"""
        return self.suggested_action in [
            SuggestedAction.PAUSE,
            SuggestedAction.COMFORT
        ]
    
    @classmethod
    def default_neutral(cls) -> "EmotionResult":
        """创建默认中性情绪结果"""
        return cls(
            emotion_type=EmotionType.NEUTRAL,
            intensity=EmotionIntensity.LOW,
            valence=EmotionValence.NEUTRAL,
            confidence=1.0,
            suggested_action=SuggestedAction.CONTINUE
        )