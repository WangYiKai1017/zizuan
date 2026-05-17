"""文件系统操作工具类

提供 MarkdownFileManager 未覆盖的文件系统操作：
删除、复制目录、重命名目录、按模式列出文件。
"""

import os
import shutil
import glob
import asyncio
from pathlib import Path
from typing import List
import logging

logger = logging.getLogger(__name__)


class FileOperations:
    """文件系统操作工具

    提供删除、复制、重命名等底层文件操作。
    所有方法为静态方法，无实例状态。
    """

    @staticmethod
    async def delete_file(path: str) -> bool:
        """异步删除单个文件

        Args:
            path: 文件的绝对路径

        Returns:
            删除成功返回 True，文件不存在返回 False
        """

        def _delete(p: str) -> bool:
            try:
                Path(p).unlink()
                return True
            except FileNotFoundError:
                return False

        result = await asyncio.to_thread(_delete, path)
        if result:
            logger.info(f"已删除文件: {path}")
        else:
            logger.warning(f"文件不存在，跳过删除: {path}")
        return result

    @staticmethod
    async def delete_files(paths: List[str]) -> int:
        """批量异步删除文件

        Args:
            paths: 文件路径列表

        Returns:
            成功删除的文件数量
        """
        results = [await FileOperations.delete_file(p) for p in paths]
        count = sum(1 for r in results if r)
        logger.info(f"批量删除完成: {count}/{len(paths)} 个文件已删除")
        return count

    @staticmethod
    def copy_directory(source: str, target: str) -> str:
        """递归复制目录

        Args:
            source: 源目录路径
            target: 目标目录路径（不能已存在）

        Returns:
            目标目录路径

        Raises:
            FileNotFoundError: 源目录不存在
            FileExistsError: 目标目录已存在
        """
        if not os.path.isdir(source):
            raise FileNotFoundError(f"源目录不存在: {source}")
        if os.path.exists(target):
            raise FileExistsError(f"目标目录已存在: {target}")
        shutil.copytree(source, target)
        file_count = sum(len(files) for _, _, files in os.walk(target))
        logger.info(f"已复制目录: {source} -> {target} ({file_count} 个文件)")
        return target

    @staticmethod
    def rename_directory(source: str, target: str) -> str:
        """重命名/移动目录

        Args:
            source: 源目录路径
            target: 目标路径

        Returns:
            新目录路径

        Raises:
            FileNotFoundError: 源目录不存在
            FileExistsError: 目标路径已存在
        """
        if not os.path.isdir(source):
            raise FileNotFoundError(f"源目录不存在: {source}")
        if os.path.exists(target):
            raise FileExistsError(f"目标路径已存在: {target}")
        Path(source).rename(target)
        logger.info(f"已重命名目录: {source} -> {target}")
        return target

    @staticmethod
    def list_files_by_pattern(directory: str, pattern: str) -> List[str]:
        """按 glob 模式列出文件

        Args:
            directory: 搜索目录
            pattern: glob 模式（如 "conversation_*.json"）

        Returns:
            匹配的文件路径列表（排序后）
        """
        search_path = os.path.join(directory, pattern)
        return sorted(glob.glob(search_path, recursive=False))

