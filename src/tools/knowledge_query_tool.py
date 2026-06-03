from typing import Optional, Dict, Any
import logging

from src.services.knowledge_base_querier import KnowledgeBaseQuerier
from src.storage.markdown_file_manager import MarkdownFileManager
from src.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


class KnowledgeQueryTool:
    """
    知识库查询工具

    职责：
    - 封装KnowledgeBaseQuerier的调用
    - 提供简洁的查询接口
    - 处理查询结果格式化

    使用场景：
    - InterviewAgent识别到关键信息时调用
    - ResumeSession分析历史对话后调用

    安全边界：
    - /biography 路径排除已在 KnowledgeBaseQuerier 层实现，
      list_files / read_file 会自动过滤并拒绝访问该路径。
    """
    
    def __init__(self, querier: KnowledgeBaseQuerier = None):
        # 使用知识库根目录作为MarkdownFileManager的base_path
        file_manager = MarkdownFileManager(base_path="./knowledge_base")
        self.querier = querier or KnowledgeBaseQuerier(
            file_manager=file_manager,
            llm_service=get_llm_service()
        )
    
    async def query(
        self,
        user_id: str,
        query: Any,
        max_iterations: int = 5
    ) -> str:
        """
        执行知识库查询
        
        Args:
            user_id: 用户ID
            query: 查询内容（可以是字符串或结构化数据）
            max_iterations: 最大迭代次数
            
        Returns:
            查询结果文本
        """
        # 提取查询文本
        if isinstance(query, dict):
            query_text = query.get("query_text", str(query))
        else:
            query_text = str(query)
        
        # 执行查询，确保target_path包含user_id
        import os
        target_path = os.path.join("./knowledge_base", user_id)
        result = await self.querier.query(
            user_input=query_text,
            target_path=target_path,
            state=None
        )
        
        # 格式化结果
        return self._format_result(result)
    
    def _format_result(self, result: Any) -> str:
        """格式化查询结果"""
        if isinstance(result, str):
            return result
        elif hasattr(result, "entries"):
            # 格式化MemoryQueryResult
            content = []
            for entry in result.entries:
                content.append(f"来自 {entry.source}：{entry.content}")
            return "\n".join(content)
        elif isinstance(result, dict):
            return result.get("content", str(result))
        else:
            return str(result)