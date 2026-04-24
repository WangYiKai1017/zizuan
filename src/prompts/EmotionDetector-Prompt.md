# EmotionDetector 动态 Prompt 模板

> 模板名称：`emotion_detection`  
> 职责：识别用户输入的情绪状态  
> 版本：v1.0  
> 日期：2026-04-19

---

## 一、Prompt 模板结构

```
## 系统角色

你是一位专业的情绪分析专家，负责识别用户对话中的情绪状态。你正在与一位老人进行采访对话，需要准确捕捉他的情绪变化。

## 任务说明

分析用户的输入，识别其当前情绪状态。你需要综合考虑：
- 用户输入的文本内容
- 最近的对话历史
- 情绪的强度和性质

## 输入信息

### 用户输入
${user_input}

### 近期对话历史
${conversation_history}

## 分析要求

1. 识别主要情绪类型（joy/pride/nostalgia/neutral/sadness/regret/anger/fear/fatigue）
2. 判断情绪强度（low/medium/high）
3. 判断情绪效价（positive/neutral/negative）
4. 提供置信度评分（0-1）
5. 建议后续行动（continue/pause/comfort/redirect）
6. 判断是否需要特殊处理

## 输出格式

请严格按照以下 JSON Schema 输出：

```json
{
  "emotion_type": "string (joy|pride|nostalgia|neutral|sadness|regret|anger|fear|fatigue)",
  "intensity": "string (low|medium|high)",
  "valence": "string (positive|neutral|negative)",
  "confidence": "number (0-1)",
  "suggested_action": "string (continue|pause|comfort|redirect)",
  "needs_special_handling": "boolean",
  "reasoning": "string (简要说明判断依据)"
}
```

## 注意事项

- 对于老人的回忆性叙述，nostalgia（怀旧）是常见情绪
- 注意区分 sadness（悲伤）和 nostalgia（怀旧）的差异
- 如果检测到 fatigue（疲劳），建议暂停对话
- 高强度负面情绪需要 special handling
```

---

## 二、动态变量说明

| 变量名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| `{user_input}` | string | ConversationTurn.user_input | 用户当前输入的文本 |
| `{conversation_history}` | string | ConversationOrchestrator 格式化 | 近3轮对话历史的格式化文本 |

### 变量格式化规则

#### user_input
直接插入原始用户输入文本。

#### conversation_history
格式化函数：`EmotionDetector._format_history()`

```python
def _format_history(self, history: List[ConversationTurn], n: int = 3) -> str:
    """格式化对话历史"""
    recent = history[-n:] if history else []
    lines = []
    for turn in recent:
        lines.append(f"用户：{turn.user_input}")
        if turn.agent_response:
            lines.append(f"助手：{turn.agent_response}")
    return "\n".join(lines) if lines else "（无历史对话）"
```

---

## 三、调用方式

### LLMService 调用代码

```python
# src/services/emotion_detector.py
async def detect(
    self,
    user_input: str,
    conversation_history: List[ConversationTurn],
) -> EmotionResult:
    # 格式化对话历史
    history_str = self._format_history(conversation_history)
    
    # 调用 LLMService
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
        return EmotionResult.default_neutral()
    
    return result
```

### LLMService 模板注册

```python
# src/services/llm_service.py
PROMPT_TEMPLATES = {
    "emotion_detection": {
        "system_prompt": "...",  # 上文的完整模板
        "output_format": "json",
        "max_tokens": 500,
    },
    # ... 其他模板
}
```

---

## 四、输出数据结构

### EmotionResult (Pydantic Model)

```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

class EmotionType(str, Enum):
    JOY = "joy"
    PRIDE = "pride"
    NOSTALGIA = "nostalgia"
    NEUTRAL = "neutral"
    SADNESS = "sadness"
    REGRET = "regret"
    ANGER = "anger"
    FEAR = "fear"
    FATIGUE = "fatigue"

class EmotionIntensity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class EmotionValence(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"

class SuggestedAction(str, Enum):
    CONTINUE = "continue"
    PAUSE = "pause"
    COMFORT = "comfort"
    REDIRECT = "redirect"

class EmotionResult(BaseModel):
    emotion_type: EmotionType
    intensity: EmotionIntensity
    valence: EmotionValence
    confidence: float = Field(ge=0, le=1)
    suggested_action: SuggestedAction
    needs_special_handling: bool
    reasoning: Optional[str] = None
    
    @classmethod
    def default_neutral(cls) -> "EmotionResult":
        return cls(
            emotion_type=EmotionType.NEUTRAL,
            intensity=EmotionIntensity.LOW,
            valence=EmotionValence.NEUTRAL,
            confidence=0.5,
            suggested_action=SuggestedAction.CONTINUE,
            needs_special_handling=False,
        )
    
    def needs_special_handling(self) -> bool:
        """判断是否需要特殊处理"""
        return (
            self.needs_special_handling or
            (self.valence == EmotionValence.NEGATIVE and self.intensity == EmotionIntensity.HIGH) or
            self.emotion_type == EmotionType.FATIGUE
        )
    
    def should_pause(self) -> bool:
        """判断是否应该暂停对话"""
        return (
            self.suggested_action == SuggestedAction.PAUSE or
            self.emotion_type == EmotionType.FATIGUE
        )
```

---

## 五、响应策略映射

根据 EmotionResult 生成响应策略：

| 情绪类型 | 强度 | 建议行动 | 响应策略 |
|----------|------|----------|----------|
| sadness/regret/anger | high | pause | 暂停对话，表达关切 |
| sadness/regret/anger | medium | comfort | 温柔安慰，可选换话题 |
| sadness/regret/anger | low | continue | 正常继续，注意语气 |
| fatigue | any | pause | 建议休息 |
| joy/pride | any | continue | 继续深入，鼓励分享 |
| nostalgia | any | continue | 顺势追问，引导展开 |
| neutral | any | continue | 正常推进 |

---

## 六、示例

### 输入示例

```
用户输入：那时候我们家很穷，但父亲总是想办法让我们吃饱...

近期对话历史：
用户：我记得小时候住在一个小院子里。
助手：那是怎样的院子呢？您还记得里面的样子吗？
用户：院子不大，但种了一棵枣树。每到秋天，我们兄弟姐妹就盼着枣子熟。
```

### 输出示例

```json
{
  "emotion_type": "nostalgia",
  "intensity": "medium",
  "valence": "neutral",
  "confidence": 0.85,
  "suggested_action": "continue",
  "needs_special_handling": false,
  "reasoning": "用户在回忆童年，语气中带有怀旧感，同时提到贫穷但父亲努力，有复杂情感但不强烈"
}
```
