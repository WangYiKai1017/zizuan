"""传记写作 Agent 集成测试

运行方式: python3 ./tests/test_biography_writing_agent.py

前提条件:
- 先运行 test_biography_outline_agent.py 生成 outline.yaml
- 手动将 outline.yaml 中的章节 status 改为 "confirmed"
- 或者本测试会自动将所有 draft 章节标记为 confirmed 以便测试

需要环境变量:
- DEEPSEEK_URL: DeepSeek API base URL
- DEEPSEEK_APIKEY: DeepSeek API key
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

TEST_KB_PATH = str(Path(__file__).parent.parent / "knowledge_base" / "test_user002")

_HAS_LLM_CREDENTIALS = bool(os.getenv("DEEPSEEK_URL") and os.getenv("DEEPSEEK_APIKEY"))


def confirm_all_draft_chapters():
    """将所有 draft 章节标记为 confirmed（用于测试）"""
    from src.services.biography_file_manager import BiographyFileManager
    from src.models.biography_models import ChapterStatus
    from datetime import datetime

    fm = BiographyFileManager(TEST_KB_PATH)
    outline = fm.load_outline()

    if not outline:
        print("错误: 未找到 outline.yaml，请先运行 test_biography_outline_agent.py")
        return False

    confirmed_count = 0
    for chapter in outline.chapters:
        if chapter.status == ChapterStatus.DRAFT:
            chapter.status = ChapterStatus.CONFIRMED
            chapter.confirmed_at = datetime.now()
            confirmed_count += 1

    if confirmed_count > 0:
        fm.save_outline(outline)
        print(f"已将 {confirmed_count} 个 draft 章节标记为 confirmed")
    else:
        # Check if any are already confirmed
        already_confirmed = sum(1 for ch in outline.chapters if ch.status == ChapterStatus.CONFIRMED)
        if already_confirmed > 0:
            print(f"已有 {already_confirmed} 个 confirmed 章节待写作")
        else:
            print("警告: 没有可写作的章节（所有章节可能已经 written）")

    return True


async def test_writing_agent_full_run():
    """测试 WritingAgent 完整运行流程"""
    from src.config.llm_config import LLMConfig
    from src.services.llm_service import LLMService
    from src.services.biography_file_manager import BiographyFileManager
    from src.services.biography_material_analyzer import BiographyMaterialAnalyzer
    from src.agents.biography_writing_agent import BiographyWritingAgent

    config = LLMConfig(
        provider="deepseek",
        model_name="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_APIKEY", ""),
        base_url=os.getenv("DEEPSEEK_URL", ""),
        temperature=0.8,  # Slightly higher for creative writing
        max_tokens=4096,
    )

    llm_service = LLMService(config)
    file_manager = BiographyFileManager(TEST_KB_PATH)
    material_analyzer = BiographyMaterialAnalyzer(file_manager)

    agent = BiographyWritingAgent(
        llm_service=llm_service,
        file_manager=file_manager,
        material_analyzer=material_analyzer,
    )

    print(f"\n{'='*60}")
    print(f"传记写作 Agent 集成测试")
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

    print(f"  已完成章节: {final_state.completed_chapters}")

    # Check output files
    chapters_dir = os.path.join(TEST_KB_PATH, "biography", "chapters")
    full_bio_path = os.path.join(TEST_KB_PATH, "biography", "full_biography.md")

    print(f"\n  章节文件:")
    if os.path.exists(chapters_dir):
        for f in sorted(os.listdir(chapters_dir)):
            filepath = os.path.join(chapters_dir, f)
            size = os.path.getsize(filepath)
            print(f"    ✓ {f} ({size} bytes)")

    print(f"\n  完整传记: {'✓ 存在' if os.path.exists(full_bio_path) else '✗ 不存在'}")

    if os.path.exists(full_bio_path):
        with open(full_bio_path, 'r', encoding='utf-8') as f:
            content = f.read()
            print(f"  完整传记字数: {len(content)} 字符")
            print(f"\n  === 传记内容预览（前1000字）===")
            print(content[:1000])
            print("...")

    print(f"\n{'='*60}")
    print("测试完成!")

    return final_state


if __name__ == "__main__":
    if not _HAS_LLM_CREDENTIALS:
        print("错误: 需要设置 DEEPSEEK_URL 和 DEEPSEEK_APIKEY 环境变量")
        sys.exit(1)

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Log to file
    log_dir = Path(__file__).parent.parent / "test_log"
    log_dir.mkdir(exist_ok=True)
    from datetime import datetime
    log_file = log_dir / f"biography_writing_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)

    print(f"日志文件: {log_file}")

    # Auto-confirm draft chapters for testing
    if not confirm_all_draft_chapters():
        sys.exit(1)

    # Run writing test
    asyncio.run(test_writing_agent_full_run())
