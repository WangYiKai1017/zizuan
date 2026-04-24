from enum import Enum


class EmotionType(str, Enum):
    """情绪类型枚举"""
    # 正向
    JOY = "joy"
    PRIDE = "pride"
    NOSTALGIA = "nostalgia"
    GRATITUDE = "gratitude"
    HOPE = "hope"
    
    # 中性
    NEUTRAL = "neutral"
    CURIOUS = "curious"
    CONTEMPLATIVE = "contemplative"
    
    # 负向
    SADNESS = "sadness"
    REGRET = "regret"
    ANGER = "anger"
    FEAR = "fear"
    GUILT = "guilt"
    
    # 特殊
    CONFUSION = "confusion"
    FATIGUE = "fatigue"
    RELUCTANCE = "reluctance"


class EmotionIntensity(str, Enum):
    """情绪强度枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EmotionValence(str, Enum):
    """情绪极性枚举"""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class SuggestedAction(str, Enum):
    """建议动作枚举"""
    CONTINUE = "continue"
    PAUSE = "pause"
    COMFORT = "comfort"
    REDIRECT = "redirect"