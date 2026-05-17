"""传记大纲规划 Agent 集成测试

运行方式: python3 ./tests/test_biography_outline_agent.py

需要环境变量:
- DEEPSEEK_URL: DeepSeek API base URL
- DEEPSEEK_APIKEY: DeepSeek API key
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

# Test configuration
TEST_KB_PATH = str(Path(__file__).parent.parent / "knowledge_base" / "test_user002")

_HAS_LLM_CREDENTIALS = bool(os.getenv("DEEPSEEK_URL") and os.getenv("DEEPSEEK_APIKEY"))


async def test_outline_agent_full_run():
    """测试 OutlineAgent 完整运行流程"""
    from src.config.llm_config import LLMConfig
    from src.services.llm_service import LLMService
    from src.services.biography_file_manager import BiographyFileManager
    from src.services.biography_material_analyzer import BiographyMaterialAnalyzer
    from src.agents.biography_outline_agent import BiographyOutlineAgent

    # Setup
    config = LLMConfig(
        provider="deepseek",
        model_name="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_APIKEY", ""),
        base_url=os.getenv("DEEPSEEK_URL", ""),
        temperature=0.7,
        max_tokens=4096,
    )

    llm_service = LLMService(config)
    file_manager = BiographyFileManager(TEST_KB_PATH)
    material_analyzer = BiographyMaterialAnalyzer(file_manager)

    agent = BiographyOutlineAgent(
        llm_service=llm_service,
        file_manager=file_manager,
        material_analyzer=material_analyzer,
    )

    print(f"\n{'='*60}")
    print(f"传记大纲规划 Agent 集成测试")
    print(f"知识库路径: {TEST_KB_PATH}")
    print(f"{'='*60}\n")

    # Run agent
    final_state = await agent.run(user_id="test_user001", kb_path=TEST_KB_PATH)

    # Print results
    print(f"\n{'='*60}")
    print(f"运行结果:")
    print(f"  状态: {final_state.status}")

    if final_state.error_message:
        print(f"  错误: {final_state.error_message}")

    if final_state.final_outline:
        outline = final_state.final_outline
        print(f"  大纲标题: {outline.title}")
        print(f"  版本: v{outline.version}")
        print(f"  章节数: {len(outline.chapters)}")
        print(f"\n  章节列表:")
        for ch in outline.chapters:
            print(f"    [{ch.status.value}] {ch.id}: {ch.title}")
            print(f"         主题: {ch.theme} | 阶段: {ch.life_stage}")
            print(f"         材料: {', '.join(ch.source_materials)}")
            print(f"         摘要: {ch.summary[:50]}...")

    if final_state.changes_made:
        print(f"\n  变更记录:")
        for change in final_state.changes_made:
            print(f"    - [{change.action}] {change.chapter_id}: {change.reason}")

    # Verify output files exist
    outline_path = os.path.join(TEST_KB_PATH, "biography", "outline.yaml")
    state_path = os.path.join(TEST_KB_PATH, "biography", ".state.json")

    print(f"\n  输出文件:")
    print(f"    outline.yaml: {'✓ 存在' if os.path.exists(outline_path) else '✗ 不存在'}")
    print(f"    .state.json:  {'✓ 存在' if os.path.exists(state_path) else '✗ 不存在'}")

    # Verify outline.yaml content
    if os.path.exists(outline_path):
        with open(outline_path, 'r', encoding='utf-8') as f:
            print(f"\n  outline.yaml 内容预览:")
            print(f"    {f.read()[:500]}...")

    print(f"\n{'='*60}")
    print("测试完成!")

    return final_state


async def test_outline_agent_incremental():
    """测试 OutlineAgent 增量模式（第二次运行无变化应跳过）"""
    from src.config.llm_config import LLMConfig
    from src.services.llm_service import LLMService
    from src.services.biography_file_manager import BiographyFileManager
    from src.services.biography_material_analyzer import BiographyMaterialAnalyzer
    from src.agents.biography_outline_agent import BiographyOutlineAgent

    config = LLMConfig(
        provider="deepseek",
        model_name="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_APIKEY", ""),
        base_url=os.getenv("DEEPSEEK_URL", ""),
        temperature=0.7,
        max_tokens=4096,
    )

    llm_service = LLMService(config)
    file_manager = BiographyFileManager(TEST_KB_PATH)
    material_analyzer = BiographyMaterialAnalyzer(file_manager)

    agent = BiographyOutlineAgent(
        llm_service=llm_service,
        file_manager=file_manager,
        material_analyzer=material_analyzer,
    )

    print(f"\n{'='*60}")
    print(f"增量模式测试（第二次运行，应跳过）")
    print(f"{'='*60}\n")

    final_state = await agent.run(user_id="test_user001", kb_path=TEST_KB_PATH)

    print(f"  状态: {final_state.status}")
    print(f"  有变更: {final_state.has_changes}")

    if not final_state.has_changes:
        print("  ✓ 正确！检测到无变化，跳过处理")
    else:
        print("  ⚠ 检测到变化，进行了处理")

    print(f"\n{'='*60}")


if __name__ == "__main__":
    if not _HAS_LLM_CREDENTIALS:
        print("错误: 需要设置 DEEPSEEK_URL 和 DEEPSEEK_APIKEY 环境变量")
        sys.exit(1)

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Also log to file
    log_dir = Path(__file__).parent.parent / "test_log"
    log_dir.mkdir(exist_ok=True)
    from datetime import datetime
    log_file = log_dir / f"biography_outline_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)

    print(f"日志文件: {log_file}")

    # Run tests
    asyncio.run(test_outline_agent_full_run())

    # Run incremental test (second run should skip)
    # asyncio.run(test_outline_agent_incremental())
