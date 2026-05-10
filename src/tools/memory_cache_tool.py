from typing import Optional, Dict, Any, List
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class MemoryCacheTool:
    """
    缓存记忆工具
    
    职责：
    - 管理会话级别的短期记忆缓存
    - 支持关键词检索
    - 支持追加更新
    
    存储结构：
    {
        "session_id": [
            {
                "content": "缓存内容",
                "tags": ["关键词1", "关键词2"],
                "timestamp": "时间戳"
            }
        ]
    }
    """
    
    def __init__(self):
        # 简化实现：使用内存存储
        # 生产环境应使用Redis等缓存服务
        self._cache: Dict[str, List[Dict]] = {}
    
    async def get_cache(
        self,
        session_id: str,
        query: Dict
    ) -> Optional[str]:
        """
        获取缓存内容
        
        Args:
            session_id: 会话ID
            query: 查询条件，包含tags等字段
            
        Returns:
            缓存内容，如果不存在返回None
        """
        if session_id not in self._cache:
            return None
        
        cache_entries = self._cache[session_id]
        query_tags = set(query.get("tags", []))
        
        # 查找匹配的缓存条目
        for entry in cache_entries:
            entry_tags = set(entry.get("tags", []))
            if query_tags & entry_tags:  # 有交集
                return entry.get("content")
        
        return None
    
    async def append_cache(
        self,
        session_id: str,
        content: str,
        tags: List[str] = None
    ):
        """
        追加缓存内容
        
        Args:
            session_id: 会话ID
            content: 缓存内容
            tags: 关键词标签
        """
        if session_id not in self._cache:
            self._cache[session_id] = []
        
        self._cache[session_id].append({
            "content": content,
            "tags": tags or [],
            "timestamp": datetime.now().isoformat()
        })
    
    async def clear_cache(self, session_id: str):
        """清空指定会话的缓存"""
        if session_id in self._cache:
            del self._cache[session_id]