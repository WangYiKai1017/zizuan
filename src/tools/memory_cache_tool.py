from typing import Optional, Dict, Any, List, Union
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


class MemoryCacheTool:
    """
    缓存记忆工具

    职责：
    - 管理会话级别的短期记忆缓存
    - 支持精确标签匹配 + 模糊关键词匹配
    - 支持追加更新
    - 支持相关性阈值过滤

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

    匹配策略（按优先级）：
    1. 精确标签集合交集（exact match）
    2. 关键词子串匹配（在 tags 或 content 中出现，fuzzy match）
    3. 按相关性排序，返回最相关条目
    4. 若匹配质量低于 relevance_threshold，则视为未命中
    """

    # 默认相关性阈值，低于该值视为未命中，强制走 KB 查询
    DEFAULT_RELEVANCE_THRESHOLD = 0.3

    def __init__(self):
        # 简化实现：使用内存存储
        # 生产环境应使用Redis等缓存服务
        self._cache: Dict[str, List[Dict]] = {}

    # ------------------------------------------------------------------ #
    # 公共接口
    # ------------------------------------------------------------------ #
    def get_cache(
        self,
        session_id: str,
        query: Union[str, Dict[str, Any], List[str]],
        relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    ) -> Optional[str]:
        """
        获取缓存内容（缓存优先模式）

        Args:
            session_id: 会话ID
            query: 查询条件，支持三种形式：
                - str: 自然语言查询，会被切分为关键词
                - dict: 兼容旧接口，包含 "tags" 字段
                - list: 关键词列表
            relevance_threshold: 相关性阈值（默认 0.3）。低于此值返回 None，
                                 强制下游执行新一轮知识库查询。

        Returns:
            最相关的缓存内容；若无满足阈值的命中则返回 None
        """
        if session_id not in self._cache:
            return None

        cache_entries = self._cache[session_id]
        if not cache_entries:
            return None

        query_tags, query_keywords = self._normalize_query(query)

        # 阶段一：精确标签集合交集
        exact_hits: List[Dict] = []
        for entry in cache_entries:
            entry_tags = set(entry.get("tags", []))
            if query_tags and (query_tags & entry_tags):
                # 交集大小越大，相关性越高
                overlap = len(query_tags & entry_tags)
                union = len(query_tags | entry_tags) or 1
                score = overlap / union  # Jaccard 相似度
                exact_hits.append({"entry": entry, "score": max(score, 0.6)})

        # 阶段二：关键词子串模糊匹配
        fuzzy_hits: List[Dict] = []
        if not exact_hits and query_keywords:
            for entry in cache_entries:
                score = self._compute_keyword_score(entry, query_keywords)
                if score > 0:
                    fuzzy_hits.append({"entry": entry, "score": score})

        # 合并并按相关性排序（精确匹配优先）
        all_hits = exact_hits + fuzzy_hits
        if not all_hits:
            return None

        all_hits.sort(key=lambda x: x["score"], reverse=True)
        best = all_hits[0]

        if best["score"] < relevance_threshold:
            logger.debug(
                f"Cache hit below relevance threshold "
                f"({best['score']:.2f} < {relevance_threshold}), forcing fresh query"
            )
            return None

        return best["entry"].get("content")

    def append_cache(
        self,
        session_id: str,
        content: str,
        tags: List[str] = None,
    ) -> None:
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
            "timestamp": datetime.now().isoformat(),
        })

    def clear_cache(self, session_id: str) -> None:
        """清空指定会话的缓存"""
        if session_id in self._cache:
            del self._cache[session_id]

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize_query(query: Union[str, Dict[str, Any], List[str], None]):
        """
        规范化查询输入，返回 (tag_set, keyword_list)。

        - tag_set: 用于精确集合匹配
        - keyword_list: 用于子串模糊匹配
        """
        if query is None:
            return set(), []

        if isinstance(query, dict):
            tags = query.get("tags", []) or []
            text = query.get("query_text", "") or ""
            keywords = list(tags)
            if text:
                keywords.extend(MemoryCacheTool._split_keywords(text))
            return set(tags), keywords

        if isinstance(query, list):
            tags = [str(t) for t in query if t]
            return set(tags), tags

        if isinstance(query, str):
            keywords = MemoryCacheTool._split_keywords(query)
            return set(keywords), keywords

        return set(), []

    @staticmethod
    def _split_keywords(text: str) -> List[str]:
        """
        将自然语言查询拆分为关键词。
        中文按 2-gram 切分 + 按非汉字分隔；英文按空白切分。
        """
        if not text:
            return []

        # 英文 / 数字以空白分割
        ascii_tokens = re.findall(r"[A-Za-z0-9_]+", text)

        # 中文连续片段
        cn_segments = re.findall(r"[\u4e00-\u9fa5]+", text)
        cn_tokens: List[str] = []
        for seg in cn_segments:
            # 整段也作为一个关键词
            if len(seg) <= 6:
                cn_tokens.append(seg)
            # 2-gram 切分
            if len(seg) >= 2:
                for i in range(len(seg) - 1):
                    cn_tokens.append(seg[i:i + 2])

        tokens = ascii_tokens + cn_tokens
        # 去重保持顺序
        seen = set()
        result = []
        for t in tokens:
            if t and t not in seen:
                seen.add(t)
                result.append(t)
        return result

    @staticmethod
    def _compute_keyword_score(entry: Dict, query_keywords: List[str]) -> float:
        """
        计算条目与查询关键词的相关性分数（0~1）。

        - 标签命中权重高于内容命中
        - 命中数量越多分数越高
        """
        if not query_keywords:
            return 0.0

        tags_text = " ".join(entry.get("tags", []) or [])
        content_text = entry.get("content", "") or ""

        tag_hits = 0
        content_hits = 0
        for kw in query_keywords:
            if not kw:
                continue
            if kw in tags_text:
                tag_hits += 1
            elif kw in content_text:
                content_hits += 1

        total_kw = len(query_keywords) or 1
        # 标签命中权重 0.7，内容命中权重 0.3
        score = (tag_hits * 0.7 + content_hits * 0.3) / total_kw
        return min(score, 1.0)
