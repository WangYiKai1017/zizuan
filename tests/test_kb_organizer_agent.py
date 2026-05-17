"""知识库整理 Agent 集成测试

使用 test_user001 知识库作为测试数据，验证完整的整理流程。
"""

import asyncio
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from src.agents.kb_organizer_agent import KBOrganizerAgent
from src.config.llm_config import LLMConfig
from src.models.kb_organizer_state import KBOrganizerState, TaskStatus
from src.services.kb_organization_service import KBOrganizationService
from src.services.llm_service import LLMService
from src.storage.file_operations import FileOperations
from src.storage.markdown_file_manager import MarkdownFileManager

TEST_KB_PATH = str(Path(__file__).parent.parent / "knowledge_base" / "test_user002")

_HAS_LLM_CREDENTIALS = bool(os.getenv("DEEPSEEK_URL") and os.getenv("DEEPSEEK_APIKEY"))


@pytest.fixture
def setup_test_kb(tmp_path):
    """Create a temporary copy of test_user001 for testing."""
    test_copy = str(tmp_path / "test_user001")
    shutil.copytree(TEST_KB_PATH, test_copy)
    yield test_copy


@pytest.fixture
def llm_service():
    """Create LLMService from environment."""
    config = LLMConfig.from_env()
    return LLMService(config)


def create_agent(llm_service: LLMService, target_path: str) -> KBOrganizerAgent:
    """Helper to create a fully-wired agent."""
    target = Path(target_path)
    parent = str(target.parent)
    folder_name = target.name

    source_fm = MarkdownFileManager(base_path=parent, conversation_id=folder_name)
    working_fm = MarkdownFileManager(base_path=parent, conversation_id=f"{folder_name}_temp")
    file_ops = FileOperations()

    # Remove the auto-created temp directory so copy_directory won't conflict
    working_path = Path(parent) / f"{folder_name}_temp"
    if working_path.exists():
        shutil.rmtree(working_path)

    service = KBOrganizationService(
        llm_service=llm_service,
        source_file_manager=source_fm,
        working_file_manager=working_fm,
        file_ops=file_ops,
    )

    return KBOrganizerAgent(
        llm_service=llm_service,
        organization_service=service,
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_LLM_CREDENTIALS, reason="LLM credentials not configured")
async def test_kb_organizer_full_pipeline(setup_test_kb, llm_service):
    """测试完整的知识库整理流程"""
    target_path = setup_test_kb
    agent = create_agent(llm_service, target_path)

    result = await agent.run(target_path)

    # Verify all tasks completed or skipped (none failed)
    for task in result.task_plan:
        assert task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED), (
            f"Task {task.task_id} ({task.task_type}) failed: {task.error}"
        )

    # Verify atomic swap happened
    assert not Path(f"{target_path}_temp").exists(), "Temp directory should be removed"
    assert Path(target_path).exists(), "Target directory should exist (swapped from temp)"

    # Verify backup was created
    parent = Path(target_path).parent
    backups = list(parent.glob("test_user001_*"))
    assert len(backups) >= 1, "Backup directory should exist"

    # Print summary
    print(f"\n{'='*60}")
    print(f"知识库整理完成!")
    print(f"  迭代次数: {result.iteration_count}")
    print(f"  合并记录: {len(result.merge_records)}")
    print(f"  矛盾问题: {len(result.conflict_items)} (未解决: {len(result.get_active_conflicts())})")
    print(f"  链接重定向: {len(result.link_redirect_map)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    """直接运行此脚本进行手动测试"""

    print("正在初始化知识库整理 Agent...")

    config = LLMConfig.from_env()
    llm_svc = LLMService(config)

    # Use real path directly (not temp copy)
    target_path = TEST_KB_PATH
    agent = create_agent(llm_svc, target_path)

    print(f"目标路径: {target_path}")
    print("开始整理...\n")

    result = asyncio.run(agent.run(target_path))

    print(f"\n完成! 状态:")
    for task in result.task_plan:
        icon = "✓" if task.status == TaskStatus.COMPLETED else "⊘" if task.status == TaskStatus.SKIPPED else "✗"
        print(f"  {icon} {task.task_id}: {task.description} → {task.result or task.error or ''}")
