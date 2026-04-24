from pydantic import BaseModel, Field
from typing import List, Optional, Any
from datetime import datetime


class MemoryEntry(BaseModel):
    """记忆条目"""
    source: str                     # 来源文件路径
    content: str                    # 内容摘要
    relevance: float                # 相关度 0-1
    memory_type: str                # short_term/long_term/profile
    metadata: dict = {}


class LinkedContent(BaseModel):
    """链接内容"""
    source: str                     # 源文件路径
    target: str                     # 目标文件路径
    content_preview: str = ""       # 内容预览
    relation: str = "related"       # 关联类型


class MemoryQueryResult(BaseModel):
    """
    记忆查询结果
    
    职责：
    - 封装记忆库查询的结果
    - 提供相关事件、人物、链接内容
    
    使用场景：
    - KnowledgeBaseQuerier.query() 的返回值
    - QuestionGenerator 生成问题的上下文
    - ContentSummarizer 归纳时的参考
    """
    
    query: str = Field(..., description="原始查询")
    query_time: datetime = Field(default_factory=datetime.now, description="查询时间")
    
    # 结果
    entries: List[MemoryEntry] = Field(default_factory=list, description="匹配的记忆条目")
    linked_content: List[LinkedContent] = Field(
        default_factory=list,
        description="通过链接关联的内容"
    )
    
    # 汇总
    total_count: int = Field(default=0, description="总结果数")
    has_results: bool = Field(default=False, description="是否有结果")
    
    def get_top_entries(self, n: int = 5) -> List[MemoryEntry]:
        """获取相关度最高的n个条目"""
        sorted_entries = sorted(self.entries, key=lambda x: x.relevance, reverse=True)
        return sorted_entries[:n]
    
    def get_events(self) -> List[MemoryEntry]:
        """获取事件类型的条目"""
        return [e for e in self.entries if "event" in e.source.lower()]
    
    def get_people(self) -> List[MemoryEntry]:
        """获取人物类型的条目"""
        return [e for e in self.entries if "people" in e.source.lower()]
    
    def has_related_events(self) -> bool:
        """是否有相关事件"""
        return len(self.get_events()) > 0
    
    @classmethod
    def empty(cls) -> "MemoryQueryResult":
        """创建空结果"""
        return cls(query="", entries=[], total_count=0, has_results=False)
    
    @classmethod
    def from_entries(cls, query: str, entries: List[MemoryEntry]) -> "MemoryQueryResult":
        """从条目列表创建"""
        return cls(
            query=query,
            entries=entries,
            total_count=len(entries),
            has_results=len(entries) > 0
        )