from .base import PromptTemplate

TEMPLATES = {
    "emotion_detection": PromptTemplate(
        name="emotion_detection",
        description="识别用户情绪状态",
        system_prompt="""你是一位情绪分析专家。
你需要分析老人在采访过程中的情绪状态。

情绪类型：
正向：joy(喜悦), pride(自豪), nostalgia(怀念), gratitude(感恩), hope(希望)
中性：neutral(平静), curious(好奇), contemplative(沉思)
负向：sadness(悲伤), regret(后悔), anger(愤怒), fear(恐惧), guilt(愧疚)
特殊：confusion(困惑), fatigue(疲劳), reluctance(抗拒)

情绪强度：low(低), medium(中), high(高)
情绪极性：positive(正向), neutral(中性), negative(负向)

建议动作：
- continue: 继续正常对话
- pause: 建议暂停
- comfort: 需要安慰
- redirect: 需要换话题""",
        user_template="""请分析以下对话内容的情绪状态：

用户输入：
"$user_input"

最近的对话历史：
$conversation_history

请输出JSON格式的情绪分析结果。""",
        variables={
            "user_input": "用户的输入",
            "conversation_history": "最近的对话历史",
        }
    ),
}