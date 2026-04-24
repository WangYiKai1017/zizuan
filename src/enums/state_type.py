from enum import Enum


class StateType(str, Enum):
    """对话状态枚举"""
    INIT = "init"                 # 初始化
    WARMUP = "warmup"             # 破冰阶段
    COLLECT = "collect"           # 采集阶段
    DEEPEN = "deepen"             # 深挖模式
    REDIRECT = "redirect"         # 重定向模式
    PAUSE = "pause"               # 暂停阶段
    HANDOFF = "handoff"           # 交接阶段