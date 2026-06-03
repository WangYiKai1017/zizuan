# src/services/knowledge_base_querier.py
from langchain.agents import create_agent
from langchain.tools import tool
from typing import List, Dict, Any
import json
import logging
import re
import asyncio

from src.services.llm_service import LLMService, get_llm_service
from src.storage.markdown_file_manager import MarkdownFileManager
from src.models import MemoryQueryResult, MemoryEntry, LinkedContent, SessionState

logger = logging.getLogger(__name__)


# 不允许访问的路径片段（传记写作模块不在指南工作范围内）
FORBIDDEN_PATH_SEGMENTS = ("biography",)


def _path_is_forbidden(path: str) -> bool:
    """判断路径是否包含被禁止访问的片段 (如 /biography)"""
    if not path:
        return False
    import os
    normalized = path.replace("\\", "/").lower()
    parts = [p for p in normalized.split("/") if p]
    for seg in FORBIDDEN_PATH_SEGMENTS:
        seg_lower = seg.lower()
        if seg_lower in parts:
            return True
        # 防护式判断：子串出现 /biography 或 biography/
        if f"/{seg_lower}" in normalized or f"{seg_lower}/" in normalized:
            # 仅当作为独立路径段时才拦截（避免误伤名为 biographies 等）
            if seg_lower in parts:
                return True
    return False


class KnowledgeBaseTools:
    """
    知识库查询工具集
    提供给 Agent 使用的工具函数

    安全边界：
    - 严禁访问 /biography 路径下的任何内容（传记写作模块独立管理）
    - list_files 过滤掉 biography 目录
    - read_file 遇到 biography 路径返回错误
    """

    def __init__(self, file_manager: MarkdownFileManager):
        self.file_manager = file_manager
        self._current_target_path = None
        self._visited_paths = set()  # 用于记录已访问的路径
        self._suspected_files = []   # 疑似相关的文件列表
        self._tool_call_count = 0    # 工具调用计数（辅助调试）
        self._tools = self._build_tools()
    
    def set_target_path(self, target_path: str) -> None:
        """设置当前目标路径"""
        self._current_target_path = target_path
    
    def get_full_path(self, relative_path: str = "") -> str:
        """获取相对于目标路径的完整路径"""
        if not self._current_target_path:
            return relative_path
        
        # 确保路径安全，防止目录遍历攻击
        if relative_path.startswith("..") or "/../" in relative_path or "\\..\\" in relative_path:
            logger.warning(f"Dangerous path detected: {relative_path}")
            return self._current_target_path
        
        import os
        full_path = os.path.normpath(os.path.join(self._current_target_path, relative_path))
        
        # # 验证路径是否在目标路径范围内
        # if not full_path.startswith(os.path.normpath(self._current_target_path)):
        #     logger.warning(f"Path traversal attempt: {relative_path}")
        #     return self._current_target_path
        
        return full_path
    
    def _build_tools(self) -> List[callable]:
        """构建 LangChain 工具"""
        # 定义工具函数
        @tool
        def list_files(path: str = "", recursive: bool = True) -> str:
            """列出指定目录下的所有文件和子目录，包含详细信息

            Args:
                path: 相对路径（相对于当前target_path）
                recursive: 是否递归列出所有子目录（默认开启）

            Returns:
                JSON格式的文件和目录列表，包含名称、类型、修改时间等信息
                /biography 相关路径会被过滤掉
            """
            try:
                self._tool_call_count += 1
                # 拒绝直接请求 biography 路径
                if _path_is_forbidden(path):
                    logger.warning(f"Blocked list_files attempt on forbidden path: {path}")
                    return json.dumps(
                        {"error": "该路径不在工作区域内", "path": path},
                        ensure_ascii=False,
                    )

                full_path = self.get_full_path(path)

                # 记录已访问的路径
                self._visited_paths.add(path)

                # 调用增强后的list_files方法，默认递归列出所有层级
                files = self.file_manager.list_files(
                    directory=path,
                    include_details=True,
                    recursive=recursive
                )

                # 过滤 /biography 路径下的任何条目
                filtered_files = []
                for item in files:
                    item_name = item.get("name", "")
                    item_path = item.get("path", "") or item.get("relative_path", "") or item_name
                    candidate = f"{path}/{item_path}" if path else item_path
                    if _path_is_forbidden(item_name) or _path_is_forbidden(item_path) or _path_is_forbidden(candidate):
                        logger.debug(f"Filtered forbidden path from list_files: {candidate}")
                        continue
                    filtered_files.append(item)

                # 对结果进行排序，目录优先，按名称排序
                def sort_key(item):
                    if item["is_dir"]:
                        return (0, item["name"])
                    else:
                        return (1, item["name"])

                filtered_files.sort(key=sort_key)

                return json.dumps(filtered_files, ensure_ascii=False, indent=2, default=str)
            except Exception as e:
                logger.error(f"Error in list_files: {e}")
                return json.dumps([], ensure_ascii=False)

        @tool
        def read_file(file_path: str) -> str:
            """读取指定文件的内容。/biography 路径不可访问。"""
            try:
                self._tool_call_count += 1
                # /biography 路径拦截
                if _path_is_forbidden(file_path):
                    logger.warning(f"Blocked read_file attempt on forbidden path: {file_path}")
                    return "该路径不在工作区域内"

                # 使用同步版本的read_file_sync避免事件循环问题
                content = self.file_manager.read_file_sync(file_path)
                return content
            except Exception as e:
                logger.error(f"Error in read_file: {e}")
                return f"无法读取文件:{file_path}，错误信息：{str(e)}"
        
        @tool
        def search_content(keyword: str, limit: int = 10) -> str:
            """在所有文件中搜索包含关键词的内容"""
            try:
                full_path = self.get_full_path()
                # 计算相对于file_manager.base_path的路径
                import os
                relative_dir = os.path.relpath(full_path, self.file_manager.base_path)
                results = asyncio.run(self.file_manager.search_files(keyword, directory=relative_dir, max_results=limit))
                return json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error in search_content: {e}")
                return json.dumps([], ensure_ascii=False)
        
        @tool
        def follow_links(file_path: str, depth: int = 1) -> str:
            """追踪文件中的Wiki链接，获取关联文件内容"""
            try:
                full_path = self.get_full_path(file_path)
                # 确保链接也在目标路径范围内
                links = asyncio.run(self.file_manager.follow_links(full_path, depth=depth))
                
                # 过滤掉目标路径范围外的链接
                valid_links = []
                for link in links:
                    if self.get_full_path(link.target) == link.target:
                        valid_links.append(link)
                
                return json.dumps([l.to_dict() for l in valid_links], ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error in follow_links: {e}")
                return json.dumps([], ensure_ascii=False)
        
        @tool
        def mark_suspected_file(file_path: str) -> str:
            """标记疑似与查询相关的文件
            
            Args:
                file_path: 相对路径（相对于当前target_path）
                
            Returns:
                操作结果
            """
            try:
                full_path = self.get_full_path(file_path)
                if file_path not in self._suspected_files:
                    self._suspected_files.append(file_path)
                    return f"已标记文件: {file_path}"
                return f"文件已被标记: {file_path}"
            except Exception as e:
                logger.error(f"Error in mark_suspected_file: {e}")
                return "标记失败"
        
        @tool
        def get_exploration_report() -> str:
            """获取路径探索报告
            
            Returns:
                JSON格式的探索报告，包含已访问的路径和标记的文件
            """
            report = {
                "visited_paths": list(self._visited_paths),
                "suspected_files": self._suspected_files,
                "total_visited": len(self._visited_paths),
                "total_suspected": len(self._suspected_files)
            }
            return json.dumps(report, ensure_ascii=False, indent=2)
        
        @tool
        def has_visited(path: str) -> str:
            """检查路径是否已被访问
            
            Args:
                path: 相对路径（相对于当前target_path）
                
            Returns:
                JSON格式的结果
            """
            result = {
                "path": path,
                "visited": path in self._visited_paths
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
        
        # 临时禁用搜索功能，注释掉search_content工具
        return [list_files, read_file, follow_links, mark_suspected_file, get_exploration_report, has_visited]
    
    @property
    def tools(self) -> List[callable]:
        return self._tools


class KnowledgeBaseQuerier:
    """
    知识库查询服务 - ReAct 模式
    
    职责：
    - 理解用户输入的查询意图
    - 使用 ReAct 模式动态查询知识库
    - 判断并返回相关的记忆上下文

    使用场景：
    - ConversationOrchestrator 每轮异步调用
    - QuestionGenerator 生成问题时参考

    调用LLMService：
    - 使用 "knowledge_base_react" 模板
    - 通过 LangChain Agent 框架实现 ReAct 循环

    迭代控制：
    - max_iterations=7：在最多 7 轮工具调用后强制输出 Final Answer
    - 递归限制 = 2 * max_iterations + 4（每轮包含 model + tool 两个节点）

    起点优先级：
    - 若 target_path 下存在 summary_index.md，则作为初始上下文注入系统提示
    """

    # 查询迭代硕段上限
    MAX_ITERATIONS: int = 7

    def __init__(
        self,
        file_manager: MarkdownFileManager,
        llm_service: LLMService = None,
    ):
        """
        初始化

        Args:
            file_manager: Markdown文件管理器
            llm_service: LLM服务（用于 ReAct Agent）
        """
        self.file_manager = file_manager
        self.llm_service = llm_service or get_llm_service()
        self.tools = KnowledgeBaseTools(file_manager)
        self._base_system_prompt: str = ""
        self.agent_graph = self._build_agent()
    
    def _build_agent(self):
        """构建 Agent"""
        # 获取 LangChain LLM
        llm = self.llm_service._model

        # 获取 ReAct Prompt 模板
        template = self.llm_service._prompt_templates.get("knowledge_base_react")
        if not template:
            raise ValueError("knowledge_base_react template not found")

        # 保存基础 system prompt，后续可动态拼接 summary_index
        self._base_system_prompt = template.system_prompt

        # 创建 Agent 图
        agent_graph = create_agent(
            model=llm,
            tools=self.tools.tools,
            system_prompt=self._base_system_prompt,
            debug=True,
        )

        return agent_graph

    def _read_summary_index(self, target_path: str) -> str:
        """读取 target_path 下的 summary_index.md，不存在则返回空串"""
        try:
            import os
            summary_path = os.path.join(target_path, "summary_index.md")
            if not os.path.exists(summary_path):
                return ""
            with open(summary_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            logger.warning(f"Failed to read summary_index.md at {target_path}: {e}")
            return ""

    def _build_system_prompt_with_summary(self, target_path: str) -> str:
        """若存在 summary_index.md，将其内容拼接到 system prompt 顶部"""
        summary_content = self._read_summary_index(target_path)
        if not summary_content:
            return self._base_system_prompt

        prefix = (
            "你已拥有以下记忆库摘要目录作为参考：\n"
            "---\n"
            f"{summary_content}\n"
            "---\n"
            "请基于此目录选择最相关的文件进行深入查阅。\n\n"
        )
        return prefix + self._base_system_prompt
    
    async def query(
        self,
        user_input: str,
        target_path: str,
        state: SessionState,
    ) -> MemoryQueryResult:
        """
        ReAct 模式查询知识库
        
        大模型通过 Thought → Action → Observation 循环：
        1. Thought: 理解用户意图，决定下一步行动
        2. Action: 调用工具（list_files/read_file/search_content/follow_links）
        3. Observation: 获取工具返回结果
        4. 循环直到判断信息足够，输出 Final Answer
        
        Args:
            user_input: 用户输入
            target_path: 知识库查询的目标路径，所有检索行为将严格限定在此路径内
            state: 会话状态
            
        Returns:
            MemoryQueryResult: 经过 LLM 判断的相关记忆
        """
        try:
            # 验证目标路径有效性
            if not target_path:
                logger.error("Target path is empty")
                return MemoryQueryResult.empty()
            
            import os
            if not os.path.exists(target_path):
                logger.error(f"Target path does not exist: {target_path}")
                return MemoryQueryResult.empty()
            
            if not os.path.isdir(target_path):
                logger.error(f"Target path is not a directory: {target_path}")
                return MemoryQueryResult.empty()
            
            # 设置目标路径
            self.tools.set_target_path(target_path)
            # 重置本轮查询的调用计数
            self.tools._tool_call_count = 0

            # 更新工具描述，包含目标路径信息
            tools_description = self._get_tools_description(target_path)

            # 尝试读取 summary_index.md 作为初始上下文
            summary_content = self._read_summary_index(target_path)

            # 构造输入消息：若存在 summary_index，作为 SystemMessage 领表拼接
            messages_payload = []
            if summary_content:
                summary_system_msg = (
                    "你已拥有以下记忆库摘要目录作为参考：\n"
                    "---\n"
                    f"{summary_content}\n"
                    "---\n"
                    "请基于此目录选择最相关的文件进行深入查阅，避免盲目遍历所有目录。"
                )
                messages_payload.append({"role": "system", "content": summary_system_msg})

            messages_payload.append({
                "role": "user",
                "content": (
                    f"{user_input}\n\n查询范围：{target_path}\n\n"
                    f"最大工具调用轮次：{self.MAX_ITERATIONS}。请高效使用每一次查询机会，"
                    f"超出后请立即输出 Final Answer。\n\n可用工具列表：\n{tools_description}"
                ),
            })

            inputs = {"messages": messages_payload}

            # 设置递归限制：每轮迭代 = model 节点 + tool 节点 ≈ 2 步，
            # 额外预留 4 步用于起始 / 收尾
            recursion_limit = self.MAX_ITERATIONS * 2 + 4

            # 使用 ainvoke 获取完整结果
            result = await self.agent_graph.ainvoke(
                inputs,
                config={"recursion_limit": recursion_limit},
            )
            
            # 获取最终响应消息
            logger.info(f"last agent result: {result["messages"][-1]}")
            logger.info(f"last agent result content: {result["messages"][-1].content}")

            final_message = result["messages"][-1]
            final_content = final_message.content
            
            # 解析最终答案
            final_answer = self._parse_final_answer(final_content)

            
            
            # 获取探索报告
            exploration_report = {
                "visited_paths": list(self.tools._visited_paths),
                "related_memories": final_answer,
                "suspected_files": self.tools._suspected_files,
                "total_visited": len(self.tools._visited_paths),
                "total_suspected": len(self.tools._suspected_files)
            }
            
            # 如果没有找到结果，添加探索报告
            if not final_answer or "related_memories" not in final_answer or not final_answer["related_memories"]:
                logger.info(f"No direct results found, returning exploration report: {exploration_report}")
                
                # 创建探索报告条目
                report_content = json.dumps(exploration_report, ensure_ascii=False, indent=2)
                exploration_entry = {
                    "source": "exploration_report",
                    "content": f"## 路径探索报告\n\n### 查询内容\n{user_input}\n\n### 探索结果\n{report_content}",
                    "relevance": 0.5,
                    "memory_type": "short_term",
                    "relevance_note": "这是路径探索的完整报告，包含所有已访问的路径和疑似相关文件"
                }
                
                if "related_memories" not in final_answer:
                    final_answer["related_memories"] = []
                
                final_answer["related_memories"].append(exploration_entry)
                final_answer["query_intent"] = user_input
                
                print("*" * 30)
                print(final_answer)
                print("*" * 30)
            
            # 构建返回结果
            result = self._build_memory_result(final_answer)
            
            # 重置访问记录和标记文件，为下一次查询做准备
            self.tools._visited_paths.clear()
            self.tools._suspected_files.clear()
            
            return result
            
        except Exception as e:
            logger.error(f"Knowledge base query failed: {e}")
            import traceback
            traceback.print_exc()
            return MemoryQueryResult.empty()
    
    def _get_tools_description(self, target_path: str) -> str:
        """获取工具列表描述"""
        return f"""
### 可用工具列表

1. **list_files** - 列出指定目录下的文件和子目录
   - 参数: path (可选子目录路径，相对于 {target_path}), recursive (是否递归列出所有子目录，默认开启)
   - 返回: JSON格式的文件和目录列表，包含名称、类型、修改时间等信息

2. **read_file** - 读取指定文件的内容
   - 参数: file_path (文件路径，相对于 {target_path})
   - 返回: 文件完整内容

3. **follow_links** - 追踪文件中的Wiki链接，获取关联文件内容
   - 参数: file_path (文件路径，相对于 {target_path}), depth (链接深度，默认1)
   - 返回: 关联文件内容列表
   - 限制: 仅返回 {target_path} 目录下的文件链接

4. **mark_suspected_file** - 标记疑似与查询相关的文件
   - 参数: file_path (文件路径，相对于 {target_path})
   - 返回: 操作结果

5. **get_exploration_report** - 获取路径探索报告
   - 参数: 无
   - 返回: JSON格式的探索报告，包含已访问的路径和标记的文件

6. **has_visited** - 检查路径是否已被访问
   - 参数: path (路径，相对于 {target_path})
   - 返回: JSON格式的结果，指示路径是否已被访问

### 查询范围

当前所有操作都将严格限制在以下目录内执行：
{target_path}

请使用相对于此目录的路径进行操作。

### 路径探索指南

1. **初始探索**：首先使用 `list_files()`（默认递归）一次性获取所有层级目录信息
2. **文件筛选**：根据获取的完整目录结构，识别与查询相关的文件
3. **完整阅读**：使用 `read_file()` 优先完整阅读并处理整个文档内容
4. **标记相关**：当发现相关文件时，使用 `mark_suspected_file("文件路径")` 进行标记
5. **链接追踪**：对标记的文件，使用 `follow_links()` 追踪关联内容
6. **探索报告**：随时可以使用 `get_exploration_report()` 获取当前的探索状态

### 探索策略

- **全面优先**：一次性获取所有层级目录信息，避免多次重复调用
- **完整阅读优先**：优先完整阅读文档内容，而非片段检索
- **相关性优先**：优先阅读和处理名称与查询关键词相关的文件

### 注意事项

- 始终使用相对路径进行操作（相对于 {target_path}）
- 优先使用 `list_files()` 一次性获取所有层级信息，避免逐个目录探索
- 优先完整阅读文档内容，确保获取完整信息
- 若未找到目标文件，请生成完整的路径探索报告
- 保持探索过程的系统性和有序性
"""
    
    def _parse_final_answer(self, output: str) -> dict:
        """解析 Final Answer
        
        处理两种情况：
        1. 标准的JSON格式输出
        2. 自然语言描述的输出（降级处理）
        """
        # 尝试提取标准的 Final Answer JSON
        match = re.search(r"Final Answer:\s*(\{.*\})", output, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse Final Answer JSON: {match.group(1)}")
                # 继续尝试其他方式
        
        # 如果没有标准JSON格式，尝试解析整个输出为JSON
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            logger.warning("Failed to parse entire output as JSON")
        
        try:
            # 降级处理：将自然语言描述转换为标准格式
            logger.info("Falling back to natural language parsing")
            
            # 提取可能的来源文件信息（支持多种格式）
            sources = []
            
            # 匹配 "文件：xxx.md" 格式
            source_matches = re.findall(r"文件[：:]\s*([^\n]+?\.md)", output, re.IGNORECASE)
            sources.extend([source.strip() for source in source_matches])
            
            # 匹配 "source: xxx.md" 格式
            source_matches = re.findall(r"source[：:]\s*([^\n]+?\.md)", output, re.IGNORECASE)
            sources.extend([source.strip() for source in source_matches])
            
            # 匹配 "来源：xxx.md" 格式
            source_matches = re.findall(r"来源[：:]\s*([^\n]+?\.md)", output, re.IGNORECASE)
            sources.extend([source.strip() for source in source_matches])
            
            # 创建标准格式的答案
            fallback_answer = {
                "query_intent": "",
                "related_memories": [
                    {
                        "source": sources[0] if sources else "unknown",
                        "content": output.strip(),
                        "relevance": "从自然语言描述中提取",
                        "memory_type": "long_term",
                        "confidence": 0.8,  # 自然语言提取的置信度较低
                        "extraction_method": "natural_language_fallback"
                    }
                ],
                "linked_context": [],
                "search_summary": "智能体未按照JSON格式输出，已从自然语言描述中提取信息"
            }
            
            return fallback_answer
            
        except Exception as e:
            logger.error(f"Error parsing final answer: {e}")
            # 最终降级：返回最小化的有效结构
            return {
                "query_intent": "",
                "related_memories": [
                    {
                        "source": "unknown",
                        "content": output.strip(),
                        "relevance": "无法解析的输出",
                        "memory_type": "long_term",
                        "confidence": 0.5
                    }
                ],
                "linked_context": [],
                "search_summary": "解析失败，已返回原始输出"
            }
    
    def _build_memory_result(self, answer: dict) -> MemoryQueryResult:
        """构建 MemoryQueryResult"""
        entries = []
        for mem in answer.get("related_memories", []):
            entries.append(MemoryEntry(
                source=mem.get("source", ""),
                content=mem.get("content", ""),
                relevance=0.9,  # LLM 已判断相关性
                memory_type=mem.get("memory_type", "long_term"),
                metadata={"relevance_note": mem.get("relevance", "")},
            ))
        
        linked = []
        for link in answer.get("linked_context", []):
            linked.append(LinkedContent(
                source=link.get("source", ""),
                target=link.get("target", ""),
                relation=link.get("relation", ""),
                content_preview="",
            ))
        
        return MemoryQueryResult(
            query=answer.get("query_intent", ""),
            entries=entries,
            linked_content=linked,
            total_count=len(entries),
            has_results=len(entries) > 0,
        )