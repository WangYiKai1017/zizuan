"""传记文件管理器

负责传记写作系统的所有文件 I/O 操作：
- outline.yaml 的读写
- .state.json 的读写
- 章节文件的读写
- 知识库材料的扫描和读取
- 全文合并输出
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from src.models.biography_models import (
    BiographyState,
    ChapterEntry,
    ChapterStatus,
    OutlineDocument,
)

logger = logging.getLogger(__name__)


class BiographyFileManager:
    """传记文件管理器

    管理 biography/ 目录下的所有文件操作。
    """

    def __init__(self, kb_path: str):
        """
        Args:
            kb_path: 知识库根路径，如 knowledge_base/test_user001
        """
        self.kb_path = kb_path
        self.biography_path = os.path.join(kb_path, "biography")
        self._ensure_directory_structure()

    def _ensure_directory_structure(self) -> None:
        """确保 biography/ 目录结构存在"""
        os.makedirs(os.path.join(self.biography_path, "chapters"), exist_ok=True)
        logger.debug("已确认 biography/ 目录结构存在: %s", self.biography_path)

    # --- outline.yaml 操作 ---

    def load_outline(self) -> Optional[OutlineDocument]:
        """读取 outline.yaml，不存在则返回 None"""
        outline_path = os.path.join(self.biography_path, "outline.yaml")
        if not os.path.exists(outline_path):
            logger.info("outline.yaml 不存在: %s", outline_path)
            return None

        try:
            with open(outline_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data is None:
                logger.warning("outline.yaml 为空文件")
                return None
            outline = OutlineDocument.model_validate(data)
            logger.info("已加载 outline.yaml，包含 %d 个章节", len(outline.chapters))
            return outline
        except Exception as e:
            logger.error("读取 outline.yaml 失败: %s", e)
            raise

    def save_outline(self, outline: OutlineDocument) -> None:
        """保存 outline.yaml"""
        outline_path = os.path.join(self.biography_path, "outline.yaml")
        try:
            data = outline.model_dump(mode="json")
            with open(outline_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    data,
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
            logger.info("已保存 outline.yaml，包含 %d 个章节", len(outline.chapters))
        except Exception as e:
            logger.error("保存 outline.yaml 失败: %s", e)
            raise

    def update_chapter_status(
        self, chapter_id: str, status: ChapterStatus, timestamp_field: str = None
    ) -> None:
        """更新单个章节的状态"""
        outline = self.load_outline()
        if outline is None:
            logger.error("无法更新章节状态：outline.yaml 不存在")
            raise FileNotFoundError("outline.yaml 不存在")

        updated = False
        for chapter in outline.chapters:
            if chapter.id == chapter_id:
                chapter.status = status
                if timestamp_field:
                    setattr(chapter, timestamp_field, datetime.now())
                updated = True
                logger.info(
                    "已更新章节 %s 状态为 %s", chapter_id, status.value
                )
                break

        if not updated:
            logger.warning("未找到章节 %s", chapter_id)
            return

        outline.last_updated = datetime.now()
        self.save_outline(outline)

    # --- .state.json 操作 ---

    def load_state(self) -> BiographyState:
        """读取 .state.json，不存在则返回默认状态"""
        state_path = os.path.join(self.biography_path, ".state.json")
        if not os.path.exists(state_path):
            logger.info(".state.json 不存在，返回默认状态")
            return BiographyState()

        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = BiographyState.model_validate(data)
            logger.info("已加载 .state.json")
            return state
        except Exception as e:
            logger.error("读取 .state.json 失败: %s", e)
            raise

    def save_state(self, state: BiographyState) -> None:
        """保存 .state.json"""
        state_path = os.path.join(self.biography_path, ".state.json")
        try:
            data = state.model_dump(mode="json")
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("已保存 .state.json")
        except Exception as e:
            logger.error("保存 .state.json 失败: %s", e)
            raise

    # --- 章节文件操作 ---

    def save_chapter(self, chapter_id: str, title: str, content: str) -> str:
        """保存章节文件，返回文件路径

        Args:
            chapter_id: 章节 ID，如 ch01
            title: 章节标题
            content: 章节 Markdown 内容

        Returns:
            保存的文件路径
        """
        safe_title = self._sanitize_filename(title)
        filename = f"{chapter_id}_{safe_title}.md"
        filepath = os.path.join(self.biography_path, "chapters", filename)

        try:
            # 如果存在同 chapter_id 的旧文件但标题不同，先删除旧文件
            existing = self._find_chapter_file(chapter_id)
            if existing and existing != filepath:
                os.remove(existing)
                logger.info("已删除旧章节文件: %s", existing)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("已保存章节文件: %s", filename)
            return filepath
        except Exception as e:
            logger.error("保存章节文件失败 %s: %s", filename, e)
            raise

    def load_chapter(self, chapter_id: str) -> Optional[str]:
        """读取章节文件内容，按 chapter_id 匹配

        Args:
            chapter_id: 章节 ID，如 ch01

        Returns:
            章节内容字符串，不存在则返回 None
        """
        filepath = self._find_chapter_file(chapter_id)
        if filepath is None:
            logger.info("未找到章节文件: %s", chapter_id)
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            logger.debug("已读取章节文件: %s", filepath)
            return content
        except Exception as e:
            logger.error("读取章节文件失败 %s: %s", chapter_id, e)
            raise

    def list_chapter_files(self) -> list[str]:
        """列出所有已写章节文件

        Returns:
            章节文件名列表
        """
        chapters_dir = os.path.join(self.biography_path, "chapters")
        if not os.path.exists(chapters_dir):
            return []

        files = [
            f
            for f in os.listdir(chapters_dir)
            if f.endswith(".md") and not f.startswith(".")
        ]
        files.sort()
        logger.debug("已列出 %d 个章节文件", len(files))
        return files

    # --- 全文合并 ---

    def merge_chapters_to_full(self, outline: OutlineDocument) -> str:
        """按大纲顺序合并所有已写章节为完整传记

        生成 full_biography.md，包含目录和所有章节内容。

        Args:
            outline: 大纲文档

        Returns:
            合并后文件的路径
        """
        output_path = os.path.join(self.biography_path, "full_biography.md")

        try:
            lines = []
            # 标题
            lines.append(f"# {outline.title}\n")
            if outline.author:
                lines.append(f"**作者：{outline.author}**\n")
            lines.append("")

            # 目录
            lines.append("## 目录\n")
            for i, chapter in enumerate(outline.chapters, 1):
                lines.append(f"{i}. [{chapter.title}](#{chapter.id})")
            lines.append("")
            lines.append("---\n")

            # 各章节内容
            for chapter in outline.chapters:
                content = self.load_chapter(chapter.id)
                if content:
                    lines.append(f'<a id="{chapter.id}"></a>\n')
                    lines.append(content)
                    lines.append("\n---\n")
                else:
                    lines.append(f'<a id="{chapter.id}"></a>\n')
                    lines.append(f"## {chapter.title}\n")
                    lines.append("*（本章尚未完成写作）*\n")
                    lines.append("\n---\n")

            full_text = "\n".join(lines)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(full_text)

            logger.info("已合并生成完整传记: %s", output_path)
            return output_path
        except Exception as e:
            logger.error("合并章节失败: %s", e)
            raise

    # --- 知识库材料扫描 ---

    def scan_kb_files(self) -> list[str]:
        """扫描知识库中所有材料文件（events/, people/, timeline/, themes/）

        排除 biography/ 目录本身。

        Returns:
            相对于 kb_path 的文件路径列表
        """
        scan_dirs = ["events", "people", "timeline", "themes"]
        result = []

        for dir_name in scan_dirs:
            dir_path = os.path.join(self.kb_path, dir_name)
            if not os.path.exists(dir_path):
                continue

            for root, _dirs, files in os.walk(dir_path):
                for filename in files:
                    if filename.endswith(".md") and not filename.startswith("."):
                        abs_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(abs_path, self.kb_path)
                        result.append(rel_path)

        result.sort()
        logger.info("扫描知识库材料文件: 共 %d 个", len(result))
        return result

    def read_kb_file(self, relative_path: str) -> str:
        """读取知识库中的单个文件

        Args:
            relative_path: 相对于 kb_path 的路径

        Returns:
            文件内容字符串
        """
        abs_path = os.path.join(self.kb_path, relative_path)
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
            logger.debug("已读取知识库文件: %s", relative_path)
            return content
        except Exception as e:
            logger.error("读取知识库文件失败 %s: %s", relative_path, e)
            raise

    def read_kb_files_by_paths(self, paths: list[str]) -> dict[str, str]:
        """批量读取知识库文件

        Args:
            paths: 相对路径列表

        Returns:
            {relative_path: file_content} 字典
        """
        result = {}
        for path in paths:
            try:
                content = self.read_kb_file(path)
                result[path] = content
            except Exception as e:
                logger.warning("跳过无法读取的文件 %s: %s", path, e)
                continue

        logger.info("批量读取知识库文件: 成功 %d / 请求 %d", len(result), len(paths))
        return result

    # --- 增量检测 ---

    def compute_kb_hash(self) -> str:
        """计算知识库内容的 SHA256 哈希值

        对所有 KB 文件路径+内容排序后计算哈希，用于检测变更。

        Returns:
            SHA256 哈希字符串
        """
        files = self.scan_kb_files()
        hasher = hashlib.sha256()

        for file_path in sorted(files):
            hasher.update(file_path.encode("utf-8"))
            try:
                content = self.read_kb_file(file_path)
                hasher.update(content.encode("utf-8"))
            except Exception as e:
                logger.warning("计算哈希时跳过文件 %s: %s", file_path, e)
                continue

        hash_value = hasher.hexdigest()
        logger.debug("知识库内容哈希: %s", hash_value[:16])
        return hash_value

    def detect_changes(self, previous_state: BiographyState) -> list[str]:
        """检测自上次运行以来新增或变更的文件

        Args:
            previous_state: 上次保存的状态

        Returns:
            新增或变更的文件相对路径列表
        """
        current_files = self.scan_kb_files()
        previous_files = set(previous_state.processed_files)

        new_files = [f for f in current_files if f not in previous_files]

        if new_files:
            logger.info("检测到 %d 个新增文件", len(new_files))
        else:
            logger.info("未检测到新增文件")

        return new_files

    # --- 内部辅助方法 ---

    def _sanitize_filename(self, title: str) -> str:
        """清理文件名中的特殊字符

        保留中文、英文、数字、下划线，其他字符替换为下划线。
        """
        # 替换空格和特殊字符为下划线
        safe = re.sub(r"[^\w\u4e00-\u9fff]", "_", title)
        # 合并多个连续下划线
        safe = re.sub(r"_+", "_", safe)
        # 去除首尾下划线
        safe = safe.strip("_")
        return safe

    def _find_chapter_file(self, chapter_id: str) -> Optional[str]:
        """根据 chapter_id 查找对应的章节文件路径"""
        chapters_dir = os.path.join(self.biography_path, "chapters")
        if not os.path.exists(chapters_dir):
            return None

        prefix = f"{chapter_id}_"
        for filename in os.listdir(chapters_dir):
            if filename.startswith(prefix) and filename.endswith(".md"):
                return os.path.join(chapters_dir, filename)

        return None

    def _serialize_datetimes(self, data) -> any:
        """递归将字典中的 datetime 对象转为 ISO 格式字符串"""
        if isinstance(data, dict):
            return {k: self._serialize_datetimes(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._serialize_datetimes(item) for item in data]
        elif isinstance(data, datetime):
            return data.isoformat()
        return data
