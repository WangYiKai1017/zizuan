import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agents.kb_organizer_agent import KBOrganizerAgent
from src.models.kb_organizer_state import KBOrganizerState, OrganizerTask
from src.services.user_kb_lock_manager import UserKBLockManager


@pytest.fixture(autouse=True)
def reset_kb_lock_manager():
    UserKBLockManager.reset()
    yield
    UserKBLockManager.reset()


@pytest.mark.asyncio
async def test_organizer_workspace_excludes_concurrent_story_outputs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "user001"
    working = tmp_path / "user001_temp"
    (source / "events/childhood").mkdir(parents=True)
    (source / "stories").mkdir(parents=True)
    (source / "events/childhood/event.md").write_text("event", encoding="utf-8")
    (source / "stories/story.md").write_text("story", encoding="utf-8")

    source_file_manager = SimpleNamespace(list_files=lambda **kwargs: [])
    agent = KBOrganizerAgent(
        llm_service=SimpleNamespace(),
        organization_service=SimpleNamespace(
            source_file_manager=source_file_manager,
        ),
    )
    state = KBOrganizerState(
        user_id="user001",
        source_path=str(source),
        working_path=str(working),
    )
    setup_task = OrganizerTask(
        task_id="task_01",
        task_type="setup_workspace",
        description="setup",
    )

    await agent._do_setup_workspace(setup_task, state)

    assert (working / "events/childhood/event.md").exists()
    assert not (working / "stories").exists()


@pytest.mark.asyncio
async def test_organizer_swap_waits_for_story_commit_and_preserves_outputs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "user001"
    working = tmp_path / "user001_temp"
    (source / "events/childhood").mkdir(parents=True)
    (source / "stories").mkdir(parents=True)
    (working / "events/childhood").mkdir(parents=True)
    (working / "stories").mkdir(parents=True)

    (source / "events/childhood/old.md").write_text("old", encoding="utf-8")
    (working / "events/childhood/organized.md").write_text("organized", encoding="utf-8")
    (working / "stories/stale.md").write_text("stale", encoding="utf-8")

    agent = KBOrganizerAgent(
        llm_service=SimpleNamespace(),
        organization_service=SimpleNamespace(),
    )
    state = KBOrganizerState(
        user_id="user001",
        source_path=str(source),
        working_path=str(working),
    )
    organizer_task = OrganizerTask(
        task_id="task_08",
        task_type="finalize_swap",
        description="finalize",
    )

    lock_manager = UserKBLockManager.get_instance()
    async with lock_manager.hold(source):
        finalize = asyncio.create_task(
            agent._do_finalize_swap(organizer_task, state)
        )
        await asyncio.sleep(0)
        assert finalize.done() is False

        (source / "stories/new-story.md").write_text("latest", encoding="utf-8")
        (source / "stories/.story_state.json").write_text(
            '{"generated_event_fingerprints": ["abc"]}',
            encoding="utf-8",
        )

    await finalize

    assert (source / "events/childhood/organized.md").read_text(encoding="utf-8") == "organized"
    assert not (source / "stories/stale.md").exists()
    assert (source / "stories/new-story.md").read_text(encoding="utf-8") == "latest"
    assert (source / "stories/.story_state.json").exists()

    backups = list(tmp_path.glob("user001_????????_??????"))
    assert len(backups) == 1
    assert (backups[0] / "stories/new-story.md").exists()
