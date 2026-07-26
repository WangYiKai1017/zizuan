from pathlib import Path

import pytest

from src.services.llm_service import LLMService


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "src" / "prompts"


def _load_runtime_prompt(filename: str) -> str:
    template = LLMService._parse_prompt_from_markdown(object(), str(PROMPTS_DIR / filename))
    assert template is not None
    return template.system_prompt


@pytest.mark.parametrize(
    "filename",
    [
        "BiographyChapterWriter-Prompt.md",
        "BiographyChapterReviewer-Prompt.md",
        "BiographyOutlinePlanner-Prompt.md",
    ],
)
def test_biography_prompts_do_not_impose_elderly_voice(filename: str) -> None:
    prompt = _load_runtime_prompt(filename)

    for banned_phrase in (
        "口述体",
        "口述自传",
        "像一位老人",
        "老人坐在",
        "同一位老人在讲话",
        "老年人回忆往事",
        "你说怪不怪",
        "那会儿啊",
    ):
        assert banned_phrase not in prompt


def test_biography_writer_uses_age_neutral_first_person_style() -> None:
    prompt = _load_runtime_prompt("BiographyChapterWriter-Prompt.md")

    assert "第一人称自传" in prompt
    assert "不刻意模仿任何年龄群体" in prompt
    assert "素材中明确记录的个人用语可以忠实保留" in prompt
    assert "建议1500-3000字" in prompt


def test_biography_reviewer_checks_for_age_stereotypes() -> None:
    prompt = _load_runtime_prompt("BiographyChapterReviewer-Prompt.md")

    assert "同一位第一人称叙述者" in prompt
    assert "年龄群体刻板表达" in prompt
    assert "原始素材和事件语境中找到依据" in prompt


def test_biography_outline_uses_first_person_autobiography_style() -> None:
    prompt = _load_runtime_prompt("BiographyOutlinePlanner-Prompt.md")

    assert "为一部第一人称自传生成章节大纲" in prompt
    assert "使用自然、清晰的自传叙述" in prompt
