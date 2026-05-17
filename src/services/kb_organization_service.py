# src/services/kb_organization_service.py
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.models.kb_organizer_state import ConflictItem, MergeRecord
from src.services.llm_service import LLMService
from src.storage.file_operations import FileOperations
from src.storage.markdown_file_manager import MarkdownFileManager

logger = logging.getLogger(__name__)


class KBOrganizationService:
    """知识库整理核心业务逻辑"""
    def __init__(
        self,
        llm_service: LLMService,
        source_file_manager: MarkdownFileManager,
        working_file_manager: MarkdownFileManager,
        file_ops: FileOperations,
    ):
        self.llm_service = llm_service
        self.source_file_manager = source_file_manager
        self.working_file_manager = working_file_manager
        self.file_ops = file_ops

    # ── 重复检测与合并 ──────────────────────────────────────

    async def find_duplicate_groups(self, file_paths: List[str], category: str) -> List[List[str]]:
        """识别语义重复/高度相似的文档组，返回应合并的文件分组"""
        summaries: List[str] = []
        for path in file_paths:
            try:
                content = await self.source_file_manager.read_file(path)
                summaries.append(f"- 文件：{path}\n  内容摘要：{content[:200]}")
            except FileNotFoundError:
                logger.warning(f"文件不存在，跳过: {path}")
        if not summaries:
            return []

        logger.info(f"[重复检测] 正在分析 {len(file_paths)} 个文件...")
        result = await self.llm_service.invoke_with_template(
            "kb_duplicate_detector",
            {"documents_summary": "\n".join(summaries), "category": category},
        )
        if not result.success:
            logger.warning(f"[重复检测] LLM 调用失败: {result.error}")
            return []
        try:
            data = self._extract_json(result.content)
            logger.info(f"[重复检测] 发现 LLM 返回数据，正在解析...")
            groups: List[List[str]] = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "files" in item:
                        files = item["files"]
                        if isinstance(files, list) and len(files) >= 2:
                            groups.append(files)
                    elif isinstance(item, list) and len(item) >= 2:
                        groups.append(item)
            elif isinstance(data, dict):
                raw_groups = data.get("groups", [])
                for item in raw_groups:
                    if isinstance(item, dict) and "files" in item:
                        files = item["files"]
                        if isinstance(files, list) and len(files) >= 2:
                            groups.append(files)
                    elif isinstance(item, list) and len(item) >= 2:
                        groups.append(item)
            logger.info(f"[重复检测] 发现 {len(groups)} 组重复文档")
            for gi, g in enumerate(groups, 1):
                logger.debug(f"[重复检测]   组{gi}: {g}")
            return groups
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"[重复检测] JSON 解析失败，LLM 返回: {result.content[:300]}")
            return []

    async def merge_documents(self, file_paths: List[str], category: str) -> MergeRecord:
        """将多个文档合并为一个，严禁丢失任何细节"""
        source_parts: List[str] = []
        for path in file_paths:
            content = await self.source_file_manager.read_file(path)
            source_parts.append(f"=== 文件：{path} ===\n{content}\n")

        result = await self.llm_service.invoke_with_template(
            "kb_document_merger",
            {
                "source_documents": "\n".join(source_parts),
                "merge_rules": "1.严禁删除任何细节；2.相同字段取并集；3.冲突字段标注来源；4.保留所有来源记录",
                "document_template": f"# {{标题}}\n\n> 类别：{category}\n\n## 内容\n\n{{合并内容}}",
            },
        )

        target_path = file_paths[0]
        logger.info(f"[文档合并] 正在合并 {len(file_paths)} 个文件 → {target_path}")
        logger.debug(f"[文档合并] 源文件: {file_paths}")
        merged_content = result.content if result.success else "\n".join(source_parts)
        if result.success:
            logger.debug(f"[文档合并] LLM 合并成功，合并内容长度: {len(merged_content)} 字符")
        else:
            logger.warning(f"[文档合并] LLM 合并失败: {result.error}，使用原始拼接")
        await self.working_file_manager.create_file(target_path, merged_content, overwrite=True)

        for path in file_paths:
            if path != target_path:
                await self.file_ops.delete_file(str(self.working_file_manager.base_path / path))

        return MergeRecord(
            merge_id=f"merge_{datetime.now().strftime('%H%M%S')}",
            source_files=file_paths,
            target_file=target_path,
            merge_reason=f"{category} 语义重复合并",
            preserved_details=[p.split("/")[-1] for p in file_paths],
        )

    # ── 矛盾检测与修复 ──────────────────────────────────────

    async def detect_contradictions(self, file_paths: List[str]) -> List[ConflictItem]:
        """扫描文档集合，识别事实矛盾"""
        doc_parts: List[str] = []
        for path in file_paths:
            try:
                content = await self.source_file_manager.read_file(path)
                doc_parts.append(f"=== {path} ===\n{content}\n")
            except FileNotFoundError:
                continue
        if not doc_parts:
            return []

        result = await self.llm_service.invoke_with_template(
            "kb_conflict_detector",
            {"documents_content": "\n".join(doc_parts), "known_facts": ""},
        )
        if not result.success:
            logger.warning(f"矛盾检测 LLM 调用失败: {result.error}")
            return []
        try:
            data = self._extract_json(result.content)
            raw_items = data if isinstance(data, list) else data.get("conflicts", [])
            return [
                ConflictItem(
                    conflict_id=f"conflict_{i:03d}",
                    conflict_type=r.get("type", r.get("conflict_type", "unknown")),
                    description=r.get("description", ""),
                    source_files=r.get("source_files", []),
                )
                for i, r in enumerate(raw_items, 1)
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"解析矛盾列表 JSON 失败: {e}")
            return []

    async def try_resolve_conflict(
        self, conflict: ConflictItem, all_documents: Dict[str, str]
    ) -> ConflictItem:
        """尝试在已有文档信息中解决矛盾"""
        evidence = "\n".join(f"=== {p} ===\n{c}" for p, c in all_documents.items())
        result = await self.llm_service.invoke_with_template(
            "kb_conflict_resolver",
            {"conflict_description": conflict.description, "evidence_documents": evidence},
        )
        if not result.success:
            return conflict
        try:
            data = self._extract_json(result.content)
            if data.get("resolvable", False):
                conflict.resolved = True
                conflict.resolution = data.get("resolution", "")
                conflict.evidence = data.get("evidence", "")
                for path, new_content in data.get("file_updates", {}).items():
                    await self.working_file_manager.create_file(path, new_content, overwrite=True)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"解析矛盾解决结果失败: {e}")
        return conflict

    # ── conflict.md 管理 ────────────────────────────────────

    async def load_conflict_file(self, path: str) -> List[ConflictItem]:
        """解析 conflict.md 中的问题列表"""
        try:
            content = await self.working_file_manager.read_file(path)
        except FileNotFoundError:
            return []

        items: List[ConflictItem] = []
        sections = re.split(r"## 问题\s+(\d+)", content)
        for i in range(1, len(sections) - 1, 2):
            num, body = sections[i], sections[i + 1]
            c_type = self._extract_field(body, "矛盾类型") or "unknown"
            desc = self._extract_field(body, "矛盾描述") or ""
            files_section = body.split("涉及文档")[1] if "涉及文档" in body else ""
            source_files = re.findall(r"`([^`]+)`", files_section)
            items.append(ConflictItem(
                conflict_id=f"conflict_{num}",
                conflict_type=c_type,
                description=desc,
                source_files=source_files,
                resolved="已解决" in body,
            ))
        return items

    async def save_conflict_file(self, path: str, conflicts: List[ConflictItem]) -> None:
        """将矛盾问题列表写入 conflict.md（标准格式）"""
        unresolved = sum(1 for c in conflicts if not c.resolved)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "# 待核实问题清单", "",
            f"> 最后更新：{now}", f"> 未解决问题数：{unresolved}", "", "---",
        ]
        for idx, c in enumerate(conflicts, 1):
            status = "已解决" if c.resolved else "待核实"
            files_md = "\n".join(f"  - `{f}`" for f in c.source_files)
            lines.extend([
                "", f"## 问题 {idx:03d}", "",
                f"- **矛盾类型**：{c.conflict_type}",
                f"- **矛盾描述**：{c.description}",
                "- **涉及文档**：", files_md,
                f"- **状态**：{status}", "", "---",
            ])
        await self.working_file_manager.create_file(path, "\n".join(lines) + "\n", overwrite=True)

    # ── 链接校验与修复 ──────────────────────────────────────

    async def validate_all_links(self, working_path: str) -> List[Dict[str, str]]:
        """校验工作目录下所有 Markdown 文件中的 Wiki 链接"""
        logger.info(f"[链接校验] 正在校验工作目录中的链接...")
        broken: List[Dict[str, str]] = []
        total_links = 0
        for item in self.working_file_manager.list_files(recursive=True):
            path = item if isinstance(item, str) else item.get("path", "")
            if not path.endswith(".md"):
                continue
            try:
                content = await self.working_file_manager.read_file(path)
            except FileNotFoundError:
                continue
            for link in self.working_file_manager.extract_wikilinks(content):
                total_links += 1
                resolved = self.working_file_manager.resolve_link(f"[[{link.target}]]", source_path=path)
                if not self.working_file_manager.file_exists(resolved):
                    broken.append({"file": path, "link": link.target, "reason": "target not found"})
                    logger.debug(f"[链接校验] 断链: {path} -> [[{link.target}]] (resolved: {resolved})")
        logger.info(f"[链接校验] 共检查 {total_links} 个链接，发现 {len(broken)} 个断链")
        return broken

    async def repair_links(self, working_path: str, redirect_map: Dict[str, str]) -> int:
        """根据重定向映射修复所有文档中的 Wiki 链接，返回修复数量"""
        repaired = 0
        for item in self.working_file_manager.list_files(recursive=True):
            path = item if isinstance(item, str) else item.get("path", "")
            if not path.endswith(".md"):
                continue
            try:
                content = await self.working_file_manager.read_file(path)
            except FileNotFoundError:
                continue
            new_content = content
            for old, new in redirect_map.items():
                # Handle [[old]] form
                if f"[[{old}]]" in new_content:
                    repaired += new_content.count(f"[[{old}]]")
                    new_content = new_content.replace(f"[[{old}]]", f"[[{new}]]")
                # Handle [[old|display_text]] form
                pattern = re.compile(r'\[\[' + re.escape(old) + r'\|([^\]]+)\]\]')
                matches = pattern.findall(new_content)
                if matches:
                    repaired += len(matches)
                    new_content = pattern.sub(lambda m: f"[[{new}|{m.group(1)}]]", new_content)
            if new_content != content:
                await self.working_file_manager.update_file(path, new_content)
        return repaired

    async def repair_broken_links_with_llm(
        self,
        broken_links: List[Dict[str, str]],
        working_path: str,
    ) -> int:
        """Use LLM to intelligently match broken links to available files.

        Returns number of links repaired.
        """
        if not broken_links:
            return 0

        # 1. Collect all valid .md file paths
        all_items = self.working_file_manager.list_files(recursive=True)
        available_files = [
            (item if isinstance(item, str) else item.get("path", ""))
            for item in all_items
        ]
        available_files = [f for f in available_files if f.endswith(".md")]
        logger.debug(f"[链接修复] 可用文件列表 ({len(available_files)} 个): {available_files}")

        # 2. Gather content snippets from files that contain broken links
        source_files = list({bl["file"] for bl in broken_links})
        file_snippets: List[str] = []
        for sf in source_files:
            try:
                content = await self.working_file_manager.read_file(sf)
                file_snippets.append(f"=== {sf} ===\n{content[:500]}\n")
            except FileNotFoundError:
                pass

        # 3. Batch broken links (up to 10 per call)
        total_repaired = 0
        batch_size = 10
        for i in range(0, len(broken_links), batch_size):
            batch = broken_links[i : i + batch_size]
            logger.info(f"[链接修复] 正在修复 {len(batch)} 个断链 (批次 {i // batch_size + 1})...")
            try:
                result = await self.llm_service.invoke_with_template(
                    "kb_link_repairer",
                    {
                        "broken_links": json.dumps(batch, ensure_ascii=False),
                        "available_files": "\n".join(f"- {f}" for f in available_files),
                        "file_contents": "\n".join(file_snippets),
                    },
                )
                if not result.success:
                    logger.warning(f"[链接修复] LLM 调用失败: {result.error}")
                    continue

                logger.debug(f"[链接修复] LLM 响应: {result.content[:500]}")
                repairs = self._extract_json(result.content)
                if not isinstance(repairs, list):
                    repairs = []
                logger.debug(f"[链接修复] 解析到 {len(repairs)} 条修复指令")

                for repair in repairs:
                    if not isinstance(repair, dict):
                        continue
                    src_file = repair.get("file", "")
                    old_link = repair.get("old_link", "")
                    new_link = repair.get("new_link", "")
                    if not (src_file and old_link and new_link):
                        continue
                    # Verify new_link is actually available
                    if new_link not in available_files:
                        logger.warning(f"[链接修复] 跳过无效目标: {new_link}")
                        continue
                    try:
                        content = await self.working_file_manager.read_file(src_file)
                    except FileNotFoundError:
                        continue
                    new_content = content
                    # Replace [[old_link]] with [[new_link]]
                    if f"[[{old_link}]]" in new_content:
                        new_content = new_content.replace(f"[[{old_link}]]", f"[[{new_link}]]")
                    # Replace [[old_link|display]] with [[new_link|display]]
                    pat = re.compile(r'\[\[' + re.escape(old_link) + r'\|([^\]]+)\]\]')
                    new_content = pat.sub(lambda m: f"[[{new_link}|{m.group(1)}]]", new_content)
                    if new_content != content:
                        await self.working_file_manager.update_file(src_file, new_content)
                        total_repaired += 1
                        logger.info(f"[链接修复] {src_file}: [[{old_link}]] → [[{new_link}]]")
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"[链接修复] 解析 LLM 响应失败: {e}")
            except Exception as e:
                logger.error(f"[链接修复] 修复过程出错: {e}", exc_info=True)

        logger.info(f"[链接修复] 成功修复 {total_repaired} 个链接")
        return total_repaired

    # ── 对话记录清理 ────────────────────────────────────────

    async def prune_conversations(self, working_path: str, keep_latest: int = 2) -> List[str]:
        """仅保留最新 N 份对话记录，删除其余"""
        deleted: List[str] = []
        json_files = self.file_ops.list_files_by_pattern(working_path, "conversation_*.json")
        log_files = self.file_ops.list_files_by_pattern(working_path + "/logs", "conversation_*.log")
        for file_list in [json_files, log_files]:
            if len(file_list) > keep_latest:
                to_delete = file_list[:-keep_latest]
                await self.file_ops.delete_files(to_delete)
                deleted.extend(to_delete)
        return deleted

    # ── 内部辅助 ────────────────────────────────────────────

    def _extract_json(self, content: str) -> Any:
        """从可能包含代码块的 LLM 响应中提取 JSON"""
        text = content.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)

    @staticmethod
    def _extract_field(text: str, field_name: str) -> Optional[str]:
        """从 Markdown 文本中提取 **字段名**：值"""
        match = re.search(rf"\*\*{field_name}\*\*[：:]\s*(.+)", text)
        return match.group(1).strip() if match else None
