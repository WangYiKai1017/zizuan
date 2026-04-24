from enum import Enum


class PhaseType(str, Enum):
    """人生阶段枚举"""
    CHILDHOOD = "childhood"       # 童年 0-12岁
    YOUTH = "youth"               # 少年 13-18岁
    YOUNG_ADULT = "young_adult"   # 青年 19-35岁
    MIDDLE_AGE = "middle_age"     # 中年 36-60岁
    ELDERLY = "elderly"           # 老年 60岁+