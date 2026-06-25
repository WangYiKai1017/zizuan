from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.profile_collection_agent import ProfileCollectionAgent


@pytest.mark.asyncio
async def test_generate_next_question_uses_json_mode_with_recent_context() -> None:
    llm = MagicMock()
    llm.invoke = AsyncMock(
        return_value=MagicMock(content='{"question": "您以前主要是做什么工作的？", "field": "occupation"}')
    )
    agent = ProfileCollectionAgent(
        user_id="trace_user",
        llm_service=llm,
        memory_manager=MagicMock(),
        initial_info={"name": "兰地", "age": "78"},
    )
    agent.conversation_history = [
        {"role": "assistant", "content": "您平时爱吃什么？"},
        {"role": "user", "content": "红烧牛肉。"},
    ]

    question = await agent._generate_next_question()

    assert question == "您以前主要是做什么工作的？"
    kwargs = llm.invoke.await_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["trace_node"] == "profile.generate_next_question"
    assert kwargs["trace_metadata"]["missing_required_fields"] == [
        "gender",
        "occupation",
        "family_status",
        "living_arrangement",
    ]
    assert kwargs["trace_metadata"]["conversation_history_turns"] == 2
    assert "【最近对话】" in kwargs["prompt"]
    assert "助手: 您平时爱吃什么？" in kwargs["prompt"]
    assert "用户: 红烧牛肉。" in kwargs["prompt"]
    assert "history" not in kwargs


@pytest.mark.asyncio
async def test_generate_next_question_rejects_invalid_target_field() -> None:
    llm = MagicMock()
    llm.invoke = AsyncMock(
        return_value=MagicMock(content='{"next_field": "phone", "question": "方便留手机号吗？"}')
    )
    agent = ProfileCollectionAgent(
        user_id="trace_user",
        llm_service=llm,
        memory_manager=MagicMock(),
        initial_info={"name": "兰地", "age": "78"},
    )

    question = await agent._generate_next_question()

    assert question == "方便问一下您的性别吗？"


@pytest.mark.asyncio
async def test_extract_info_fallback_fills_missing_occupation_without_name() -> None:
    llm = MagicMock()
    llm.invoke = AsyncMock(
        return_value=MagicMock(content='{"fields": {}}')
    )
    agent = ProfileCollectionAgent(
        user_id="trace_user",
        llm_service=llm,
        memory_manager=MagicMock(),
        initial_info={"name": "兰地", "age": "78"},
    )

    result = await agent._extract_info("我是程序员啊")

    assert result["occupation"] == "程序员"
    assert "name" not in result


def test_normalize_fields_ignores_removed_story_expectation_aliases() -> None:
    agent = ProfileCollectionAgent(
        user_id="trace_user",
        llm_service=MagicMock(),
        memory_manager=MagicMock(),
    )

    normalized = agent._normalize_fields({
        "写作目标": "把教书经历留给孩子",
        "记录期望": "记录家庭故事",
    })

    assert "story_expectation" not in normalized


def test_fallback_does_not_extract_removed_story_expectation() -> None:
    agent = ProfileCollectionAgent(
        user_id="trace_user",
        llm_service=MagicMock(),
        memory_manager=MagicMock(),
    )

    fields = agent._fallback_extract_info("我想把这辈子的教书和成家的事都留给孩子们，也想让孙辈知道我们怎么过来的。")

    assert "story_expectation" not in fields


@pytest.mark.asyncio
async def test_extract_info_fallback_does_not_override_llm_or_collected_fields() -> None:
    llm = MagicMock()
    llm.invoke = AsyncMock(
        return_value=MagicMock(content='{"fields": {"occupation": "软件工程师", "name": "兰地"}}')
    )
    agent = ProfileCollectionAgent(
        user_id="trace_user",
        llm_service=llm,
        memory_manager=MagicMock(),
        initial_info={"name": "微信姓名", "age": "78", "occupation": "已收集职业"},
    )

    result = await agent._extract_info("我是程序员啊，我叫张三")

    assert result == {}


def test_profile_phase_decision_is_observed_with_output() -> None:
    agent = ProfileCollectionAgent(
        user_id="trace_user",
        llm_service=MagicMock(),
        memory_manager=MagicMock(),
        initial_info={
            "name": "兰地",
            "age": "78",
            "gender": "男",
            "occupation": "退休教师",
            "family_status": "与老伴同住",
            "living_arrangement": "上海，与老伴同住",
        },
    )
    observation = MagicMock()
    captured = {}

    @contextmanager
    def fake_observe_step(node, **kwargs):
        captured["node"] = node
        captured["kwargs"] = kwargs
        yield observation

    with patch("src.agents.profile_collection_agent.observe_step", fake_observe_step):
        decision = agent._observe_profile_phase_decision(trigger="after_extract")

    assert captured["node"] == "profile.phase_decision"
    assert captured["kwargs"]["as_type"] == "tool"
    assert decision["is_complete"] is True
    assert decision["next_phase"] == "interview"
    assert decision["reason"] == "all_required_fields_complete"
    observation.update.assert_called_once_with(output=decision)
