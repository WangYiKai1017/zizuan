"""Guided initial interview flow control.

This controller keeps the early interview focused on a static question plan
without turning the main InterviewAgent prompt into a priority soup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import logging

from src.config.initial_interview_questions import INITIAL_INTERVIEW_QUESTIONS
from src.services.llm_service import LLMService
from src.services.observability import observe_step
from src.services.question_generator import QuestionResult

logger = logging.getLogger(__name__)


GUIDED_STATE_FILENAME = "guided_initial_state.json"
MAX_FOLLOWUPS_PER_GUIDED_QUESTION = 2


@dataclass
class GuidedDecision:
    """A generated question plus updated guided state."""

    result: QuestionResult
    guided_completed: bool


class GuidedInitialInterviewController:
    """Manage the guided first-pass interview plan and persisted progress."""

    def __init__(
        self,
        user_id: str,
        llm_service: LLMService,
        knowledge_base_root: str | Path | None = None,
        questions: Optional[List[Dict[str, str]]] = None,
    ):
        self.user_id = user_id
        self.llm_service = llm_service
        self.knowledge_base_root = Path(knowledge_base_root) if knowledge_base_root else (
            Path(__file__).resolve().parent.parent.parent / "knowledge_base"
        )
        self.questions = questions or INITIAL_INTERVIEW_QUESTIONS
        self.question_by_id = {q["id"]: q for q in self.questions}
        self.state_path = self.knowledge_base_root / self.user_id / GUIDED_STATE_FILENAME

    def ensure_state(self) -> Dict[str, Any]:
        """Load an existing state or create a fresh one."""
        state = self.load_state()
        self.save_state(state)
        return state

    def load_state(self) -> Dict[str, Any]:
        """Load guided state, rebuilding it if missing or malformed."""
        if not self.state_path.exists():
            return self._initial_state()

        try:
            raw = self.state_path.read_text(encoding="utf-8")
            state = json.loads(raw)
            if self._is_valid_state(state):
                return self._normalize_state(state)
        except Exception as e:
            logger.warning("Failed to load guided initial state for %s: %s", self.user_id, e)

        logger.warning("Rebuilding malformed guided initial state for %s", self.user_id)
        return self._initial_state()

    def save_state(self, state: Dict[str, Any]) -> None:
        """Persist guided state."""
        state = self._normalize_state(state)
        state["updated_at"] = datetime.now().isoformat()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_completed(self) -> bool:
        return bool(self.load_state().get("guided_completed"))

    def is_active(self) -> bool:
        return not self.is_completed()

    def build_start_message(
        self,
        address_style: str = "您",
        resume_summary: str | None = None,
    ) -> Optional[str]:
        """Return a deterministic opening for the current guided question."""
        state = self.ensure_state()
        if state.get("guided_completed"):
            return None

        question = self._current_question(state)
        if not question:
            state["guided_completed"] = True
            self.save_state(state)
            return None

        address = address_style or "您"
        if resume_summary:
            snippet = str(resume_summary).strip()
            snippet = snippet[:80]
            return (
                f"{address}，欢迎回来。上次我们聊到的内容我还记着，"
                f"{snippet}。这次我们接着往下聊：{question['question']}"
            )

        return f"好的，我大概了解您了。那我们先从小时候聊起吧，{question['question']}"

    async def generate_next(
        self,
        user_input: str,
        memory_context: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
        candidate_questions: Optional[List[Dict[str, str]]] = None,
        address_style: str = "您",
    ) -> GuidedDecision:
        """Generate the next guided question and update persisted progress."""
        state = self.ensure_state()
        if state.get("guided_completed"):
            return GuidedDecision(
                result=QuestionResult(
                    question="您能再详细说说吗？",
                    source="generated",
                    candidate_question_id=None,
                ),
                guided_completed=True,
            )

        current_question = self._current_question(state)
        if not current_question:
            state["guided_completed"] = True
            self.save_state(state)
            return GuidedDecision(
                result=QuestionResult(
                    question=self._free_interview_transition(address_style),
                    source="generated",
                    candidate_question_id=None,
                    topic_switched=True,
                    new_topic="自由采访",
                ),
                guided_completed=True,
            )

        if state.get("current_question_followup_count", 0) >= MAX_FOLLOWUPS_PER_GUIDED_QUESTION:
            before_state = dict(state)
            with observe_step(
                "guided.advance_to_next_question",
                as_type="tool",
                input={
                    "reason": "max_followups_reached",
                    "state": before_state,
                    "current_question": current_question,
                    "max_followups": MAX_FOLLOWUPS_PER_GUIDED_QUESTION,
                },
                metadata={
                    "reason": "max_followups_reached",
                    "current_question_id": current_question.get("id") if current_question else None,
                    "followup_count": before_state.get("current_question_followup_count", 0),
                },
            ) as observation:
                result = self._advance_to_next_question(state, address_style)
                if observation is not None:
                    observation.update(output={
                        "question": result.question,
                        "source": result.source,
                        "candidate_question_id": result.candidate_question_id,
                        "topic_switched": result.topic_switched,
                        "new_topic": result.new_topic,
                        "guided_completed": state.get("guided_completed", False),
                        "next_question_id": state.get("current_question_id"),
                    })
            return GuidedDecision(result=result, guided_completed=state.get("guided_completed", False))

        prompt = self._build_prompt(
            user_input=user_input,
            memory_context=memory_context,
            state=state,
            current_question=current_question,
            candidate_questions=candidate_questions,
            address_style=address_style,
        )

        try:
            llm_result = await self.llm_service.invoke(
                prompt=prompt,
                temperature=0.7,
                history=conversation_history,
                response_format={"type": "json_object"},
                trace_node="guided.generate_next",
            )
            decision = self._parse_decision(llm_result.content, candidate_questions)
        except Exception as e:
            logger.warning("Guided question generation failed for %s: %s", self.user_id, e)
            decision = {
                "question": f"{address_style or '您'}能再多讲一点当时的细节吗？",
                "source": "generated",
                "candidate_question_id": None,
                "guided_question_completed": False,
                "move_to_next_guided_question": False,
            }

        if decision["guided_question_completed"] or decision["move_to_next_guided_question"]:
            state["completed_question_ids"] = self._append_unique(
                state.get("completed_question_ids", []),
                current_question["id"],
            )
            state["current_question_followup_count"] = 0
            next_question = self._next_question_after(state, current_question["id"])
            if next_question:
                state["current_question_id"] = next_question["id"]
            else:
                state["guided_completed"] = True
        else:
            state["current_question_followup_count"] = state.get("current_question_followup_count", 0) + 1

        self.save_state(state)
        return GuidedDecision(
            result=QuestionResult(
                question=decision["question"],
                source=decision["source"],
                candidate_question_id=decision["candidate_question_id"],
                topic_switched=bool(decision.get("topic_switched", False)),
                new_topic=decision.get("new_topic"),
            ),
            guided_completed=bool(state.get("guided_completed")),
        )

    def _initial_state(self) -> Dict[str, Any]:
        first_question_id = self.questions[0]["id"] if self.questions else None
        return {
            "guided_completed": not bool(first_question_id),
            "current_question_id": first_question_id,
            "completed_question_ids": [],
            "current_question_followup_count": 0,
            "updated_at": datetime.now().isoformat(),
        }

    def _is_valid_state(self, state: Any) -> bool:
        if not isinstance(state, dict):
            return False
        if "guided_completed" not in state:
            return False
        if not isinstance(state.get("completed_question_ids", []), list):
            return False
        current_id = state.get("current_question_id")
        if current_id is not None and current_id not in self.question_by_id:
            return False
        return True

    def _normalize_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(state)
        completed = [
            qid for qid in normalized.get("completed_question_ids", [])
            if qid in self.question_by_id
        ]
        normalized["completed_question_ids"] = completed
        normalized["guided_completed"] = bool(normalized.get("guided_completed"))
        if normalized.get("current_question_id") not in self.question_by_id:
            next_question = self._first_uncompleted_question(completed)
            normalized["current_question_id"] = next_question["id"] if next_question else None
            normalized["guided_completed"] = next_question is None
        try:
            followup_count = int(normalized.get("current_question_followup_count", 0))
        except (TypeError, ValueError):
            followup_count = 0
        normalized["current_question_followup_count"] = max(0, followup_count)
        return normalized

    def _current_question(self, state: Dict[str, Any]) -> Optional[Dict[str, str]]:
        current_id = state.get("current_question_id")
        if current_id in self.question_by_id:
            return self.question_by_id[current_id]
        return self._first_uncompleted_question(state.get("completed_question_ids", []))

    def _first_uncompleted_question(self, completed_ids: List[str]) -> Optional[Dict[str, str]]:
        completed = set(completed_ids)
        for question in self.questions:
            if question["id"] not in completed:
                return question
        return None

    def _next_question_after(self, state: Dict[str, Any], current_id: str) -> Optional[Dict[str, str]]:
        completed = set(state.get("completed_question_ids", []))
        seen_current = False
        for question in self.questions:
            if question["id"] == current_id:
                seen_current = True
                continue
            if seen_current and question["id"] not in completed:
                return question
        return self._first_uncompleted_question(list(completed))

    def _advance_to_next_question(self, state: Dict[str, Any], address_style: str) -> QuestionResult:
        current_question = self._current_question(state)
        if current_question:
            state["completed_question_ids"] = self._append_unique(
                state.get("completed_question_ids", []),
                current_question["id"],
            )
        next_question = self._next_question_after(state, current_question["id"]) if current_question else None
        state["current_question_followup_count"] = 0

        if next_question:
            state["current_question_id"] = next_question["id"]
            self.save_state(state)
            return QuestionResult(
                question=(
                    f"那我们先把这段放一放，接着往下聊聊。"
                    f"{address_style or '您'}，{next_question['question']}"
                ),
                source="generated",
                candidate_question_id=None,
                topic_switched=True,
                new_topic=next_question.get("stage_label") or next_question["stage"],
            )

        state["guided_completed"] = True
        state["current_question_id"] = None
        self.save_state(state)
        return QuestionResult(
            question=self._free_interview_transition(address_style),
            source="generated",
            candidate_question_id=None,
            topic_switched=True,
            new_topic="自由采访",
        )

    def _free_interview_transition(self, address_style: str) -> str:
        address = address_style or "您"
        return (
            f"{address}，刚才这些回忆已经把人生几个重要阶段都串起来了。"
            "接下来我们可以顺着您最想多讲的地方慢慢展开，您现在最想从哪段经历继续聊？"
        )

    def _build_prompt(
        self,
        user_input: str,
        memory_context: Optional[str],
        state: Dict[str, Any],
        current_question: Dict[str, str],
        candidate_questions: Optional[List[Dict[str, str]]],
        address_style: str,
    ) -> str:
        candidate_questions_formatted = "无"
        if candidate_questions:
            candidate_questions_formatted = "\n".join(
                f"{i}. [{cq['id']}] {cq['question']}"
                for i, cq in enumerate(candidate_questions, 1)
            )

        remaining_questions = [
            q for q in self.questions
            if q["id"] not in set(state.get("completed_question_ids", []))
        ]
        remaining_formatted = "\n".join(
            f"- [{q['id']}] {q.get('stage_label') or q['stage']} ({q['stage']})：{q['question']}"
            for q in remaining_questions[:5]
        )
        current_focus = current_question.get("focus") or "无"
        current_stage_label = current_question.get("stage_label") or current_question["stage"]

        return f"""## 任务
你正在执行初期受控采访。请只围绕当前预设问题做判断，不要自由发散太远。

## 当前预设问题
- id: {current_question['id']}
- 阶段: {current_stage_label} ({current_question['stage']})
- 问题: {current_question['question']}
- 挖掘方向: {current_focus}
- 当前问题已追问次数: {state.get('current_question_followup_count', 0)}
- 每个预设问题最多追问次数: {MAX_FOLLOWUPS_PER_GUIDED_QUESTION}

## 用户刚才的回答
{user_input}

## 记忆上下文
{memory_context or '无'}

## 强相关候选问题
{candidate_questions_formatted}

## 后续预设问题顺序参考
{remaining_formatted or '无'}

## 对被采访者的称呼
{address_style or '您'}

## 决策规则
1. 如果用户已经给出当前预设问题的具体细节，可以自然过渡到下一个预设问题。
2. 如果当前回答很笼统，并且追问次数还没有达到上限，可以温和地换个角度追问当前问题。
3. 如果候选问题和用户刚才主动提到的内容强相关，可以把候选问题改写成当前话题下的一句追问；这种情况 source 必须是 candidate_question。
4. 如果用户提到强情绪、亲人离世、疾病、创伤或重大转折，先接住并短暂追问，不要硬切题。
5. 不要说“固定问题”“清单”“业务分析师”或“候选问题”。
6. 输出的问题必须自然、口语化、亲切。

## 输出格式
只输出 JSON：
{{
  "question": "最终问出去的问题文本",
  "source": "generated" 或 "candidate_question",
  "candidate_question_id": "候选问题id或null",
  "guided_question_completed": true 或 false,
  "move_to_next_guided_question": true 或 false,
  "topic_switched": true 或 false,
  "new_topic": "新话题描述或null"
}}
"""

    def _parse_decision(
        self,
        content: Any,
        candidate_questions: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        if isinstance(content, dict):
            parsed = content
        else:
            parsed = json.loads(str(content).strip())

        question = str(parsed.get("question", "")).strip()
        if not question:
            question = "您能再多讲一点当时的细节吗？"

        source = parsed.get("source", "generated")
        qid = parsed.get("candidate_question_id")
        if source not in ("generated", "candidate_question"):
            source = "generated"
            qid = None

        if source == "candidate_question":
            valid_ids = {cq["id"] for cq in candidate_questions or []}
            if not qid or qid not in valid_ids:
                source = "generated"
                qid = None

        return {
            "question": question,
            "source": source,
            "candidate_question_id": qid,
            "guided_question_completed": bool(parsed.get("guided_question_completed", False)),
            "move_to_next_guided_question": bool(parsed.get("move_to_next_guided_question", False)),
            "topic_switched": bool(parsed.get("topic_switched", False)),
            "new_topic": parsed.get("new_topic"),
        }

    def _append_unique(self, values: List[str], value: str) -> List[str]:
        result = list(values or [])
        if value and value not in result:
            result.append(value)
        return result
