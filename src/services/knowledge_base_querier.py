# src/services/knowledge_base_querier.py
"""
知识库查询服务 - 两步式工作流（File Selection + Concurrent Read & Answer）

替代了原有的 ReAct 多轮迭代实现，避免长时间延迟与 SSE 超时：
1. Step 1 — File Selection：基于 summary_index.md 与用户查询，由 LLM 选出最相关的文件路径列表
2. Step 2 — Concurrent Read + Answer：并发读取所选文件，组装上下文后由 LLM 生成最终答案
"""

from typing import Dict, List, Optional
import asyncio
import json
import logging
import os
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.services.llm_service import LLMService, get_llm_service
from src.storage.markdown_file_manager import MarkdownFileManager
from src.models import LinkedContent, MemoryEntry, MemoryQueryResult, SessionState

logger = logging.getLogger(__name__)


# 不允许访问的路径片段（传记写作模块不在指南工作范围内）
FORBIDDEN_PATH_SEGMENTS = ("biography",)


def _path_is_forbidden(path: str) -> bool:
    """判断路径是否包含被禁止访问的片段 (如 /biography)"""
    if not path:
        return False
    normalized = path.replace("\\", "/").lower()
    parts = [p for p in normalized.split("/") if p]
    for seg in FORBIDDEN_PATH_SEGMENTS:
        seg_lower = seg.lower()
        if seg_lower in parts:
            return True
        # 防护式判断：子串出现 /biography 或 biography/
        if f"/{seg_lower}" in normalized or f"{seg_lower}/" in normalized:
            if seg_lower in parts:
                return True
    return False


class KnowledgeBaseTools:
    """
    知识库查询辅助工具（两步式工作流配套）

    职责：
    - 提供基于 target_path 的文件读取辅助方法（带路径校验）

    安全边界：
    - 严禁访问 /biography 路径下的任何内容（传记写作模块独立管理）
    - read_file 遇到 biography 路径返回错误
    """

    def __init__(self, file_manager: MarkdownFileManager):
        self.file_manager = file_manager
        self._current_target_path: Optional[str] = None

    def set_target_path(self, target_path: str) -> None:
        """设置当前目标路径"""
        self._current_target_path = target_path

    def get_full_path(self, relative_path: str = "") -> str:
        """获取相对于目标路径的完整路径，包含基础的目录遍历防护"""
        if not self._current_target_path:
            return relative_path

        if relative_path.startswith("..") or "/../" in relative_path or "\\..\\" in relative_path:
            logger.warning(f"Dangerous path detected: {relative_path}")
            return self._current_target_path

        return os.path.normpath(os.path.join(self._current_target_path, relative_path))

    def read_file(self, file_path: str) -> str:
        """
        读取指定文件的内容（同步）。

        Args:
            file_path: 相对于 target_path 的相对路径，或绝对路径

        Returns:
            文件内容；若路径被禁止或读取失败，则返回带错误说明的字符串
        """
        try:
            if _path_is_forbidden(file_path):
                logger.warning(f"Blocked read_file attempt on forbidden path: {file_path}")
                return "该路径不在工作区域内"

            # 若给定相对路径，将其解析为相对于 target_path 的绝对路径
            if os.path.isabs(file_path):
                full_path = file_path
            else:
                full_path = self.get_full_path(file_path)

            return self.file_manager.read_file_sync(full_path)
        except Exception as e:
            logger.error(f"Error in read_file({file_path}): {e}")
            return f"无法读取文件:{file_path}，错误信息：{str(e)}"


class KnowledgeBaseQuerier:
    """
    知识库查询服务 - 两步式工作流

    工作流程：
    - Step 1 (File Selection)：读取 summary_index.md，连同用户查询发给 LLM；
      LLM 输出最相关文件相对路径的 JSON 数组（最多 8 个）。
    - Step 2 (Concurrent Read + Answer)：使用 asyncio.gather() 并发读取所有选中文件，
      然后由 LLM 基于这些内容生成结构化的 JSON 答案。

    安全边界：
    - 任何包含 /biography 的路径会被拒绝。
    """

    # 单次查询允许选择的最大文件数
    MAX_FILES: int = 8

    def __init__(
        self,
        file_manager: MarkdownFileManager,
        llm_service: LLMService = None,
    ):
        """
        Args:
            file_manager: Markdown文件管理器
            llm_service: LLM服务（包含 LangChain ChatModel）
        """
        self.file_manager = file_manager
        self.llm_service = llm_service or get_llm_service()
        # 直接复用底层 LangChain ChatModel，对应原实现中 self.llm_service._model
        self.llm = self.llm_service._model
        self.tools = KnowledgeBaseTools(file_manager)

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------
    async def query(
        self,
        user_input: str,
        target_path: str,
        state: SessionState,
    ) -> MemoryQueryResult:
        """
        两步式知识库查询。

        Args:
            user_input: 用户输入的查询内容
            target_path: 知识库根目录（限定查询范围）
            state: 会话状态（保留参数兼容旧接口）

        Returns:
            MemoryQueryResult: 经过 LLM 判断的相关记忆
        """
        try:
            # 1. 校验目标路径
            if not target_path:
                logger.error("Target path is empty")
                return MemoryQueryResult.empty()

            if _path_is_forbidden(target_path):
                logger.warning(f"Blocked query attempt on forbidden target_path: {target_path}")
                return MemoryQueryResult.empty()

            if not os.path.exists(target_path):
                logger.error(f"Target path does not exist: {target_path}")
                return MemoryQueryResult.empty()

            if not os.path.isdir(target_path):
                logger.error(f"Target path is not a directory: {target_path}")
                return MemoryQueryResult.empty()

            self.tools.set_target_path(target_path)

            # 2. 读取 summary_index.md
            summary_index = self._read_summary_index(target_path)
            if not summary_index:
                logger.warning(f"summary_index.md not found or empty under: {target_path}")
                return MemoryQueryResult(
                    query=user_input,
                    entries=[],
                    linked_content=[],
                    total_count=0,
                    has_results=False,
                )

            # 3. Step 1: 文件选择
            selected_files = await self._select_files(user_input, summary_index)
            logger.info(f"[KB Querier] Selected files ({len(selected_files)}): {selected_files}")

            if not selected_files:
                return MemoryQueryResult(
                    query=user_input,
                    entries=[],
                    linked_content=[],
                    total_count=0,
                    has_results=False,
                )

            # 4. Step 2: 并发读取文件
            file_contents = await self._read_files_concurrently(target_path, selected_files)
            if not file_contents:
                logger.warning("[KB Querier] No file contents available after concurrent read")
                return MemoryQueryResult(
                    query=user_input,
                    entries=[],
                    linked_content=[],
                    total_count=0,
                    has_results=False,
                )

            # 5. Step 2 (cont.): 让 LLM 基于内容回答
            answer = await self._generate_answer(user_input, file_contents)
            return self._build_memory_result(answer)

        except Exception as e:
            logger.error(f"Knowledge base query failed: {e}")
            import traceback
            traceback.print_exc()
            return MemoryQueryResult.empty()

    # ------------------------------------------------------------------
    # Step 1: 文件选择
    # ------------------------------------------------------------------
    async def _select_files(self, user_input: str, summary_index: str) -> List[str]:
        """调用 LLM 基于 summary_index 选出最相关的文件路径列表"""
        messages = self._build_file_selection_prompt(summary_index, user_input)

        config = self.llm_service.build_langchain_config(
            trace_node="knowledge_base.file_selection",
            trace_tags=["knowledge_base", "file_selection"],
        )

        try:
            response = await self.llm.ainvoke(messages, config=config)
        except Exception as e:
            logger.error(f"[KB Querier] File selection LLM call failed: {e}")
            return []

        content = getattr(response, "content", "") or ""
        files = self._extract_json_array(content)

        # 过滤非法/被禁止的路径，并截断到 MAX_FILES
        cleaned: List[str] = []
        seen = set()
        for item in files:
            if not isinstance(item, str):
                continue
            path = item.strip().lstrip("/")
            if not path or path in seen:
                continue
            if _path_is_forbidden(path):
                logger.debug(f"[KB Querier] Skipped forbidden path from selection: {path}")
                continue
            cleaned.append(path)
            seen.add(path)
            if len(cleaned) >= self.MAX_FILES:
                break

        return cleaned

    def _build_file_selection_prompt(
        self, summary_index: str, query: str
    ) -> List:
        """构建 Step 1 的消息列表"""
        system = (
            "你是一个记忆库文件选择助手。根据用户的查询需求和记忆库摘要目录，"
            "选择最相关的文件（最多8个）。"
        )
        user = (
            "## 记忆库摘要目录\n"
            f"{summary_index}\n\n"
            "## 用户查询\n"
            f"{query}\n\n"
            "## 输出要求\n"
            "请直接输出一个JSON数组，包含最相关的文件路径（相对路径）。"
            "只输出JSON，不要有其他内容。\n"
            "示例：[\"events/childhood/event1.md\", \"people/family/father.md\"]"
        )
        return [SystemMessage(content=system), HumanMessage(content=user)]

    # ------------------------------------------------------------------
    # Step 2: 并发读取 + 回答生成
    # ------------------------------------------------------------------
    async def _read_files_concurrently(
        self, target_path: str, relative_paths: List[str]
    ) -> Dict[str, str]:
        """并发读取所有选中文件，失败的文件会被静默跳过"""

        async def _read_one(rel_path: str) -> tuple[str, Optional[str]]:
            if _path_is_forbidden(rel_path):
                return rel_path, None
            try:
                content = await asyncio.to_thread(self.tools.read_file, rel_path)
                if isinstance(content, str) and content.startswith("无法读取文件"):
                    logger.warning(f"[KB Querier] Skip unreadable file: {rel_path}")
                    return rel_path, None
                if content == "该路径不在工作区域内":
                    return rel_path, None
                return rel_path, content
            except Exception as e:
                logger.warning(f"[KB Querier] Failed to read {rel_path}: {e}")
                return rel_path, None

        results = await asyncio.gather(
            *[_read_one(p) for p in relative_paths], return_exceptions=False
        )

        contents: Dict[str, str] = {}
        for path, content in results:
            if content is not None:
                contents[path] = content
        return contents

    async def _generate_answer(
        self, user_input: str, file_contents: Dict[str, str]
    ) -> dict:
        """调用 LLM 根据并发读取到的文件内容生成最终答案"""
        messages = self._build_answer_generation_prompt(user_input, file_contents)

        config = self.llm_service.build_langchain_config(
            trace_node="knowledge_base.answer_generation",
            trace_tags=["knowledge_base", "answer_generation"],
            trace_metadata={"file_count": len(file_contents)},
        )

        try:
            response = await self.llm.ainvoke(messages, config=config)
        except Exception as e:
            logger.error(f"[KB Querier] Answer generation LLM call failed: {e}")
            return {
                "query_intent": user_input,
                "related_memories": [],
                "linked_context": [],
                "search_summary": f"LLM 调用失败：{e}",
            }

        content = getattr(response, "content", "") or ""
        return self._parse_final_answer(content)

    def _build_answer_generation_prompt(
        self, query: str, file_contents: Dict[str, str]
    ) -> List:
        """构建 Step 2 的消息列表"""
        formatted_blocks = []
        for path, content in file_contents.items():
            formatted_blocks.append(
                f"### 文件：{path}\n"
                f"```\n{content}\n```"
            )
        formatted_file_contents = "\n\n".join(formatted_blocks) if formatted_blocks else "（无可用文件内容）"

        system = "你是一个记忆库查询助手。根据以下文件内容回答用户的查询。"
        user = (
            "## 用户查询\n"
            f"{query}\n\n"
            "## 相关文件内容\n"
            f"{formatted_file_contents}\n\n"
            "## 输出要求\n"
            "请以JSON格式输出查询结果：\n"
            "{\n"
            "  \"query_intent\": \"用户查询意图的简要描述\",\n"
            "  \"related_memories\": [\n"
            "    {\n"
            "      \"source\": \"文件路径\",\n"
            "      \"content\": \"相关内容摘要\",\n"
            "      \"relevance\": \"相关性说明\",\n"
            "      \"memory_type\": \"long_term\"\n"
            "    }\n"
            "  ],\n"
            "  \"linked_context\": [],\n"
            "  \"search_summary\": \"搜索总结\"\n"
            "}"
        )
        return [SystemMessage(content=system), HumanMessage(content=user)]

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _read_summary_index(self, target_path: str) -> str:
        """读取 target_path 下的 summary_index.md，不存在则返回空串"""
        try:
            summary_path = os.path.join(target_path, "summary_index.md")
            if not os.path.exists(summary_path):
                return ""
            with open(summary_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            logger.warning(f"Failed to read summary_index.md at {target_path}: {e}")
            return ""

    def _extract_json_array(self, text: str) -> List:
        """从 LLM 响应中提取 JSON 数组，兼容 ```json``` 包裹等情况"""
        if not text:
            return []

        candidate = text.strip()

        # 处理 ```json ... ``` 代码块
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", candidate)
        if fence_match:
            candidate = fence_match.group(1).strip()

        # 直接尝试解析
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # 尝试在文本中定位首个 JSON 数组片段
        bracket_match = re.search(r"\[[\s\S]*\]", candidate)
        if bracket_match:
            try:
                data = json.loads(bracket_match.group(0))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                logger.warning(f"[KB Querier] Failed to parse JSON array fragment: {bracket_match.group(0)[:200]}")

        logger.warning(f"[KB Querier] No JSON array found in response: {text[:200]}")
        return []

    def _parse_final_answer(self, output: str) -> dict:
        """
        解析最终答案 JSON。

        兼容三种情况：
        1. 带 ```json``` 代码块包裹的 JSON
        2. 纯 JSON 文本
        3. 解析失败时的降级处理
        """
        if not output:
            return self._fallback_answer("", "LLM 返回内容为空")

        candidate = output.strip()

        # 去除 ```json``` / ``` 包裹
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", candidate)
        if fence_match:
            candidate = fence_match.group(1).strip()

        # 直接解析
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # 兜底：在文本中寻找首个 JSON 对象
        obj_match = re.search(r"\{[\s\S]*\}", candidate)
        if obj_match:
            try:
                data = json.loads(obj_match.group(0))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                logger.warning(
                    f"[KB Querier] Failed to parse final answer JSON object: {obj_match.group(0)[:200]}"
                )

        return self._fallback_answer(output, "LLM 输出未能解析为 JSON")

    def _fallback_answer(self, raw_output: str, reason: str) -> dict:
        """生成解析失败时的降级答案，保持调用方下游兼容"""
        logger.warning(f"[KB Querier] Falling back final answer: {reason}")
        return {
            "query_intent": "",
            "related_memories": [
                {
                    "source": "unknown",
                    "content": raw_output.strip(),
                    "relevance": reason,
                    "memory_type": "long_term",
                }
            ] if raw_output else [],
            "linked_context": [],
            "search_summary": reason,
        }

    def _build_memory_result(self, answer: dict) -> MemoryQueryResult:
        """将原始字典封装为 MemoryQueryResult"""
        entries = []
        for mem in answer.get("related_memories", []) or []:
            entries.append(
                MemoryEntry(
                    source=mem.get("source", ""),
                    content=mem.get("content", ""),
                    relevance=0.9,  # LLM 已判断相关性
                    memory_type=mem.get("memory_type", "long_term"),
                    metadata={"relevance_note": mem.get("relevance", "")},
                )
            )

        linked = []
        for link in answer.get("linked_context", []) or []:
            linked.append(
                LinkedContent(
                    source=link.get("source", ""),
                    target=link.get("target", ""),
                    relation=link.get("relation", ""),
                    content_preview="",
                )
            )

        return MemoryQueryResult(
            query=answer.get("query_intent", ""),
            entries=entries,
            linked_content=linked,
            total_count=len(entries),
            has_results=len(entries) > 0,
        )
