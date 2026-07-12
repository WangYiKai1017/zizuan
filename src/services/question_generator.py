# src/services/question_generator.py
from typing import List, Optional, Dict
from dataclasses import dataclass
import json
import logging

from src.services.llm_service import LLMService, get_llm_service
from src.models import EmotionResult, MemoryQueryResult, SessionState
from src.enums import PhaseType

logger = logging.getLogger(__name__)


@dataclass
class QuestionResult:
    """Result of generating the next interview question."""
    question: str
    source: str  # "generated" | "candidate_question"
    candidate_question_id: Optional[str] = None
    topic_switched: bool = False
    new_topic: Optional[str] = None


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
        conversation_history: Optional[List[Dict]] = None,
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
            return await self._generate_emotion_response(user_input, emotion, conversation_history)

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
        conversation_history: Optional[List[Dict]] = None,
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
            history=conversation_history  # 传递对话历史
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

    async def generate_next(
        self,
        user_input: str,
        memory_context: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
        candidate_questions: Optional[List[Dict[str, str]]] = None,
        should_switch_topic: bool = False,
        current_topic: Optional[str] = None,
        topic_turn_count: int = 0,
        topic_history: Optional[List[str]] = None,
        address_style: str = "您",
    ) -> QuestionResult:
        """
        生成下一个问题（InterviewAgent专用接口）

        Args:
            user_input: 用户输入
            memory_context: 记忆上下文
            conversation_history: 对话历史
            candidate_questions: 候选问题列表，每项包含 id 和 question

        Returns:
            QuestionResult，包含问题文本和来源信息
        """
        # 格式化候选问题
        candidate_questions_formatted = "无"
        if candidate_questions:
            lines = []
            for i, cq in enumerate(candidate_questions, 1):
                lines.append(f"{i}. [{cq['id']}] {cq['question']}")
            candidate_questions_formatted = "\n".join(lines)

        # 构建话题上下文
        topic_context = ""
        if current_topic:
            history_str = ', '.join(topic_history[-5:]) if topic_history else '无'
            topic_context = f"""\n## 当前话题状态\n- 当前话题: {current_topic}\n- 已讨论轮次: {topic_turn_count}\n- 历史话题: {history_str}\n"""
            if should_switch_topic:
                topic_context += f"""- ⚠️ 建议换话题: 当前话题已讨论较久，请评估是否需要自然过渡到新话题。\n  - 如果被采访者的回答越来越短或重复，果断换话题\n  - 如果被采访者仍在分享新的重要细节，可以再追问1-2次\n  - 换话题时要自然过渡，不要突兀\n  - 避免重复已聊过的话题: {history_str}\n"""

        # 构建问题生成prompt
        prompt = f"""## 任务
基于用户的回答、记忆上下文和候选问题列表，决定下一个采访问题。

## 用户回答
{user_input}

## 记忆上下文
{memory_context or "无"}

## 记忆使用规则
- 如果记忆上下文中有与用户当前表达相关的内容，先用一句话自然接住其中的具体事实，再提出一个问题
- 不要把已经召回的内容当成第一次听说，也不要让用户重复已经记录过的信息
- 有相关记忆时，不要说“不记得”“没有印象”或类似表述
- 如果记忆上下文为“无”，不要声称记得或忘记，只基于用户当前表达自然追问
- 最终回复可以包含一句简短回应和一个问题，但一次只问一个问题

## 候选问题（家属提前准备但尚未询问）
{candidate_questions_formatted}
{topic_context}
## 对被采访者的称呼
{address_style or "您"}
在问题正文中可以自然地使用此称呼（如"{address_style}，那时候..."），但不要在问题开头加"称呼，"的前缀。

## 规则
1. 如果某个候选问题与用户刚才的回答明显相关，选择该问题并改写成自然、温和的追问。
2. 改写时不要照搬原话，要像采访者根据上下文自然追问。
3. 不要说"你子女想问"或类似表达。
4. 不要强行插入不相关的候选问题。
5. 一次最多使用一个候选问题。
6. 如果没有明显相关的候选问题，生成一个自然的采访追问。

## 回忆方向
- 用户的回答里同时有轻松温暖和困难失落的线索时，优先追问轻松、温暖、有趣、有成就感的线索
- 用户提到困难时，优先了解帮助过他的人、支撑他的力量、采取的行动或后来的转机，不追问痛苦有多深
- 不主动引出遗憾、伤害、失望、羞愧或关系破裂等经历
- 如果用户主动谈到痛苦经历，先简短接住他的感受，再尊重他的叙述方向；不要强行乐观，也不要连续深挖创伤细节
- 候选问题带有明显负面预设时，将它改写为关注支持、行动或转机的自然问法；无法自然改写则本轮不使用

## 输出格式（JSON）
{{
  "question": "最终问出去的问题文本",
  "source": "candidate_question" 或 "generated",
  "candidate_question_id": "q1" 或 null,
  "topic_switched": true 或 false,
  "new_topic": "新话题描述" 或 null
}}
"""

        # 调用LLM生成问题，传递对话历史，要求JSON输出
        result = await self.llm_service.invoke(
            prompt=prompt,
            temperature=0.7,
            history=conversation_history,  # 传递对话历史
            response_format={"type": "json_object"},
        )

        if result.success:
            content = result.content.strip()
            try:
                if isinstance(content, dict):
                    parsed = content
                else:
                    parsed = json.loads(content)

                question = parsed.get("question", "")
                source = parsed.get("source", "generated")
                qid = parsed.get("candidate_question_id")
                topic_switched = parsed.get("topic_switched", False)
                new_topic = parsed.get("new_topic")

                if not question:
                    # 降级：如果 question 为空，使用默认问题
                    return QuestionResult(
                        question="您能再详细说说吗？",
                        source="generated",
                        candidate_question_id=None,
                    )

                # 校验 source 合法性
                if source not in ("candidate_question", "generated"):
                    source = "generated"
                    qid = None

                # 如果 source 是 candidate_question，但 qid 不在候选列表中，降级为 generated
                if source == "candidate_question" and candidate_questions:
                    valid_ids = {cq["id"] for cq in candidate_questions}
                    if qid not in valid_ids:
                        source = "generated"
                        qid = None

                return QuestionResult(
                    question=question,
                    source=source,
                    candidate_question_id=qid,
                    topic_switched=bool(topic_switched),
                    new_topic=new_topic,
                )
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning(f"Failed to parse question generation JSON: {e}. Content: {content[:200]}")
                # 降级：直接使用返回的文本作为问题
                return QuestionResult(
                    question=content if content else "您能再详细说说吗？",
                    source="generated",
                    candidate_question_id=None,
                )
        else:
            # 降级：使用默认问题
            return QuestionResult(
                question="您能再详细说说吗？",
                source="generated",
                candidate_question_id=None,
            )
