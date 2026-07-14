from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.agents.biography_outline_agent import BiographyOutlineAgent
from src.agents.biography_writing_agent import BiographyWritingAgent
from src.models.biography_models import (
    BiographyState,
    ChapterEntry,
    ChapterStatus,
    OutlineDocument,
)
from src.models.biography_outline_state import OutlineAgentState
from src.models.biography_writing_state import WritingAgentState


def _chapter(
    chapter_id: str,
    title: str,
    *,
    theme: str = "人生回望",
    life_stage: str = "elderly",
    sources: list[str] | None = None,
    status: ChapterStatus = ChapterStatus.DRAFT,
) -> ChapterEntry:
    return ChapterEntry(
        id=chapter_id,
        title=title,
        life_stage=life_stage,
        theme=theme,
        source_materials=sources or [],
        summary=f"{title}摘要",
        status=status,
        confirmed_at=datetime(2026, 6, 20) if status != ChapterStatus.DRAFT else None,
        written_at=datetime(2026, 6, 21) if status == ChapterStatus.WRITTEN else None,
    )


def _agent() -> tuple[BiographyOutlineAgent, MagicMock]:
    file_manager = MagicMock()
    file_manager.compute_kb_hash.return_value = "kb-hash"
    file_manager.scan_kb_files.return_value = []
    agent = BiographyOutlineAgent(
        llm_service=MagicMock(),
        file_manager=file_manager,
        material_analyzer=MagicMock(),
    )
    return agent, file_manager


def _state(
    *,
    current: list[ChapterEntry] | None,
    proposed: list[ChapterEntry],
    changed_files: list[str] | None = None,
) -> OutlineAgentState:
    outline = None
    if current is not None:
        outline = OutlineDocument(
            title="我的人生故事",
            author="测试用户",
            version=2,
            chapters=current,
        )
    return OutlineAgentState(
        user_id="test_user",
        current_outline=outline,
        proposed_chapters=proposed,
        changed_files=changed_files or [],
    )


@pytest.mark.asyncio
async def test_incremental_outline_reuses_existing_id_for_exact_duplicate():
    agent, _ = _agent()
    sources = ["events/elderly/独居生活.md", "people/family/女儿.md"]
    existing = _chapter(
        "ch07",
        "独居回望：喧嚣落尽后的自我确认",
        sources=sources,
        status=ChapterStatus.WRITTEN,
    )
    duplicate = _chapter(
        "ch09",
        "独居回望：喧嚣落尽后的自我确认",
        sources=sources,
    )

    result = await agent.diff_and_update_node(
        _state(current=[existing], proposed=[duplicate])
    )

    assert [chapter.id for chapter in result["final_outline"].chapters] == ["ch07"]
    assert result["final_outline"].chapters[0].status == ChapterStatus.WRITTEN
    assert not any(change.action == "add" for change in result["changes_made"])


@pytest.mark.asyncio
async def test_existing_duplicates_keep_more_mature_chapter():
    agent, _ = _agent()
    sources = ["events/elderly/独居生活.md"]
    written = _chapter(
        "ch07",
        "独居回望",
        sources=sources,
        status=ChapterStatus.WRITTEN,
    )
    confirmed = _chapter(
        "ch09",
        "独居回望",
        sources=sources,
        status=ChapterStatus.CONFIRMED,
    )

    result = await agent.diff_and_update_node(
        _state(current=[written, confirmed], proposed=[])
    )

    assert [chapter.id for chapter in result["final_outline"].chapters] == ["ch07"]
    removal = next(
        change for change in result["changes_made"]
        if change.action == "remove_duplicate"
    )
    assert removal.chapter_id == "ch09"
    assert "ch07" in removal.reason


@pytest.mark.asyncio
async def test_scan_routes_existing_duplicates_to_repair_without_kb_changes():
    agent, file_manager = _agent()
    sources = ["events/elderly/独居生活.md"]
    written = _chapter(
        "ch07",
        "独居回望",
        sources=sources,
        status=ChapterStatus.WRITTEN,
    )
    confirmed = _chapter(
        "ch09",
        "独居回望",
        sources=sources,
        status=ChapterStatus.CONFIRMED,
    )
    file_manager.load_state.return_value = BiographyState(
        kb_content_hash="kb-hash"
    )
    file_manager.load_outline.return_value = OutlineDocument(
        chapters=[written, confirmed]
    )

    result = await agent.scan_kb_node(OutlineAgentState(user_id="test_user"))
    next_step = agent.should_continue_after_scan(
        OutlineAgentState.model_validate(result)
    )

    assert result["has_changes"] is False
    assert result["needs_outline_repair"] is True
    assert next_step == "repair"
    agent.material_analyzer.scan_and_parse_all.assert_not_called()


@pytest.mark.asyncio
async def test_writing_loader_repairs_confirmed_duplicate_of_written_chapter():
    sources = [
        "events/elderly/开始独居生活.md",
        "events/elderly/离婚.md",
        "people/protagonist.md",
        "timeline/life-events.md",
    ]
    written = _chapter(
        "ch07",
        "独居回望：喧嚣落尽后的自我确认",
        theme="繁华过后的沉淀与接纳",
        sources=sources,
        status=ChapterStatus.WRITTEN,
    )
    confirmed = _chapter(
        "ch09",
        "独居回望：喧嚣落尽后的自我确认",
        theme="繁华过后的沉淀与接纳",
        sources=sources,
        status=ChapterStatus.CONFIRMED,
    )
    outline = OutlineDocument(chapters=[written, confirmed], version=2)
    file_manager = MagicMock()
    file_manager.load_outline.return_value = outline
    agent = BiographyWritingAgent(
        llm_service=MagicMock(),
        file_manager=file_manager,
        material_analyzer=MagicMock(),
    )

    result = await agent.load_tasks_node(WritingAgentState(user_id="test_user"))

    assert result["chapters_to_write"] == []
    assert [chapter.id for chapter in outline.chapters] == ["ch07"]
    file_manager.save_outline.assert_called_once_with(outline)
    file_manager.merge_chapters_to_full.assert_called_once_with(outline)


@pytest.mark.asyncio
async def test_same_material_can_support_distinct_themes():
    agent, _ = _agent()
    shared_sources = [
        "events/youth/求学经历.md",
        "people/family/父亲.md",
    ]
    existing = _chapter(
        "ch02",
        "父亲送我去上学",
        theme="父子关系",
        life_stage="youth",
        sources=shared_sources,
    )
    distinct = _chapter(
        "ch09",
        "第一次离开家乡",
        theme="独立成长",
        life_stage="youth",
        sources=shared_sources,
    )

    result = await agent.diff_and_update_node(
        _state(current=[existing], proposed=[distinct])
    )

    assert [chapter.id for chapter in result["final_outline"].chapters] == [
        "ch02",
        "ch09",
    ]


@pytest.mark.asyncio
async def test_semantic_match_updates_draft_but_preserves_identity():
    agent, _ = _agent()
    sources = ["events/middle_age/钳工比赛.md"]
    existing = _chapter(
        "ch04",
        "车间里的那些年",
        theme="职业成长",
        life_stage="middle_age",
        sources=sources,
    )
    proposed = _chapter(
        "ch10",
        "从学徒到钳工",
        theme="职业成长",
        life_stage="middle_age",
        sources=sources,
    )

    result = await agent.diff_and_update_node(
        _state(current=[existing], proposed=[proposed])
    )

    chapter = result["final_outline"].chapters[0]
    assert chapter.id == "ch04"
    assert chapter.title == "从学徒到钳工"
    assert chapter.status == ChapterStatus.DRAFT
    assert [change.action for change in result["changes_made"]] == ["update"]


@pytest.mark.asyncio
async def test_new_material_marks_matching_written_chapter_outdated():
    agent, _ = _agent()
    old_source = "events/middle_age/钳工比赛.md"
    new_source = "events/middle_age/技术改造.md"
    existing = _chapter(
        "ch04",
        "车间里的那些年",
        theme="职业成长",
        life_stage="middle_age",
        sources=[old_source],
        status=ChapterStatus.WRITTEN,
    )
    proposed = _chapter(
        "ch10",
        "车间里的那些年",
        theme="职业成长",
        life_stage="middle_age",
        sources=[old_source, new_source],
    )

    result = await agent.diff_and_update_node(
        _state(
            current=[existing],
            proposed=[proposed],
            changed_files=[new_source],
        )
    )

    chapter = result["final_outline"].chapters[0]
    assert chapter.id == "ch04"
    assert chapter.status == ChapterStatus.OUTDATED
    assert chapter.source_materials == [old_source, new_source]
    assert any(
        change.action == "mark_outdated" and change.chapter_id == "ch04"
        for change in result["changes_made"]
    )


@pytest.mark.asyncio
async def test_changed_existing_material_records_outdated_transition():
    agent, _ = _agent()
    source = "events/middle_age/钳工比赛.md"
    existing = _chapter(
        "ch04",
        "车间里的那些年",
        theme="职业成长",
        life_stage="middle_age",
        sources=[source],
        status=ChapterStatus.WRITTEN,
    )
    proposed = _chapter(
        "ch04",
        "车间里的那些年",
        theme="职业成长",
        life_stage="middle_age",
        sources=[source],
    )

    result = await agent.diff_and_update_node(
        _state(
            current=[existing],
            proposed=[proposed],
            changed_files=[source],
        )
    )

    assert result["final_outline"].chapters[0].status == ChapterStatus.OUTDATED
    assert [change.action for change in result["changes_made"]] == [
        "mark_outdated"
    ]


@pytest.mark.asyncio
async def test_first_run_deduplicates_content_and_repairs_duplicate_ids():
    agent, _ = _agent()
    sources = ["events/childhood/小学.md"]
    first = _chapter(
        "ch01",
        "小学时光",
        theme="求学",
        life_stage="childhood",
        sources=sources,
    )
    duplicate = _chapter(
        "ch08",
        "小学时光",
        theme="求学",
        life_stage="childhood",
        sources=sources,
    )
    distinct_same_id = _chapter(
        "ch01",
        "青年入厂",
        theme="职业起点",
        life_stage="youth",
        sources=["events/youth/入厂.md"],
    )

    result = await agent.diff_and_update_node(
        _state(current=None, proposed=[first, duplicate, distinct_same_id])
    )

    chapters = result["final_outline"].chapters
    assert len(chapters) == 2
    assert len({chapter.id for chapter in chapters}) == 2
    assert {chapter.title for chapter in chapters} == {"小学时光", "青年入厂"}
