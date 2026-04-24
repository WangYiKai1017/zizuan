from enum import Enum


class StrategyType(str, Enum):
    """采访策略枚举"""
    SPARKLE_FIRST = "sparkle_first"           # 闪光点优先
    TIMELINE_CLASSIC = "timeline_classic"     # 时间线经典
    THEMATIC_DIVERGENT = "thematic_divergent" # 主题式发散