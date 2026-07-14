import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.kb_organizer_state import ConflictItem, ConflictResolutionBatch
from src.services.kb_organization_service import KBOrganizationService
from src.services.llm_service import LLMCallResult


def make_service(tmp_path: Path, responses: list[list[dict]]) -> tuple[KBOrganizationService, AsyncMock]:
    llm = SimpleNamespace(invoke_structured=AsyncMock())
    llm.invoke_structured.side_effect = [
        (
            ConflictResolutionBatch.model_validate({"results": response}),
            LLMCallResult(success=True, content=json.dumps({"results": response}, ensure_ascii=False)),
        )
        for response in responses
    ]
    working_manager = SimpleNamespace(
        base_path=tmp_path,
        create_file=AsyncMock(),
    )
    service = KBOrganizationService(
        llm_service=llm,
        source_file_manager=SimpleNamespace(),
        working_file_manager=working_manager,
        file_ops=SimpleNamespace(),
    )
    return service, llm.invoke_structured


@pytest.mark.asyncio
async def test_resolve_conflicts_batches_and_limits_evidence(tmp_path):
    conflicts = [
        ConflictItem(
            conflict_id=f"conflict_{index:03d}",
            conflict_type="relationship",
            description=f"矛盾 {index}",
            source_files=[f"events/event_{index}.md"],
        )
        for index in range(1, 7)
    ]
    documents = {
        **{f"events/event_{index}.md": f"相关证据 {index}" for index in range(1, 7)},
        "events/unrelated.md": "不应发送给模型",
    }
    responses = [
        [
            {
                "conflict_id": conflict.conflict_id,
                "resolvable": False,
                "resolution": "证据不足",
            }
            for conflict in conflicts[:5]
        ],
        [{"conflict_id": conflicts[5].conflict_id, "resolvable": False}],
    ]
    service, invoke = make_service(tmp_path, responses)

    result = await service.resolve_conflicts(conflicts, documents)

    assert len(result) == 6
    assert invoke.await_count == 2
    for call in invoke.await_args_list:
        variables = call.args[1]
        assert "不应发送给模型" not in variables["evidence_documents"]
    assert invoke.await_args_list[0].kwargs["trace_metadata"] == {
        "batch_index": 1,
        "conflict_count": 5,
        "evidence_file_count": 5,
    }
    assert invoke.await_args_list[0].kwargs["output_model"] is ConflictResolutionBatch


@pytest.mark.asyncio
async def test_resolve_conflicts_applies_only_allowed_file_updates(tmp_path):
    conflict = ConflictItem(
        conflict_id="conflict_001",
        conflict_type="time",
        description="年份不一致",
        source_files=["events/a.md", "events/b.md"],
    )
    response = [{
        "conflict_id": "conflict_001",
        "resolvable": True,
        "resolution": "以明确日期为准",
        "evidence": "events/a.md 有明确日期",
        "file_updates": {
            "events/b.md": "修正内容",
            "user.md": "越权内容",
        },
    }]
    service, _ = make_service(tmp_path, [response])

    result = await service.resolve_conflicts(
        [conflict],
        {"events/a.md": "2020 年", "events/b.md": "2021 年", "user.md": "用户"},
    )

    assert result[0].resolved is True
    service.working_file_manager.create_file.assert_awaited_once_with(
        "events/b.md",
        "修正内容",
        overwrite=True,
    )


def test_conflict_has_new_evidence_uses_file_mtime(tmp_path):
    conflict_file = tmp_path / "conflict.md"
    evidence_file = tmp_path / "events" / "a.md"
    evidence_file.parent.mkdir()
    evidence_file.write_text("证据", encoding="utf-8")
    conflict_file.write_text("冲突", encoding="utf-8")
    service, _ = make_service(tmp_path, [])
    conflict = ConflictItem(
        conflict_id="conflict_001",
        conflict_type="time",
        description="年份不一致",
        source_files=["events/a.md"],
    )

    os.utime(evidence_file, ns=(1_000_000_000, 1_000_000_000))
    os.utime(conflict_file, ns=(2_000_000_000, 2_000_000_000))
    assert service.conflict_has_new_evidence(conflict) is False

    os.utime(evidence_file, ns=(3_000_000_000, 3_000_000_000))
    assert service.conflict_has_new_evidence(conflict) is True


def test_normalize_relative_path_rejects_paths_outside_knowledge_base():
    assert KBOrganizationService._normalize_relative_path("events/a.md") == "events/a.md"
    assert KBOrganizationService._normalize_relative_path("./events/a.md") == "events/a.md"
    assert KBOrganizationService._normalize_relative_path("../user.md") == ""
    assert KBOrganizationService._normalize_relative_path("/etc/passwd") == ""
