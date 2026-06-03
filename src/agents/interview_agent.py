from typing import Optional, Dict, Any, List
from datetime import datetime
import logging
import json

from src.services.llm_service import LLMService, get_llm_service
from src.services.memory_manager import MemoryManager
from src.services.question_generator import QuestionGenerator, QuestionResult
from src.tools import MemoryCacheTool, KnowledgeQueryTool, MemoryArchiveTool
from src.models import SessionState, ConversationTurn
from src.storage.memory_repository import MemoryRepository

logger = logging.getLogger(__name__)


class InterviewAgent:
    """
    主体采访Agent
    
    职责：
    - 问题生成与对话引导
    - 知识库查询与缓存管理
    - 关键信息识别与追踪
    
    使用Prompt：QuestionGenerator-Prompt.md
    
    核心流程：
    提问 → 回答 → 识别关键信息 → 查询知识库 → 更新缓存 → 继续
    """
    
    def __init__(
        self,
        user_id: str,
        llm_service: LLMService = None,
        memory_manager: MemoryManager = None,
        cache_tool: MemoryCacheTool = None,
        query_tool: KnowledgeQueryTool = None,
        archive_tool: MemoryArchiveTool = None,
        resume_prompt: str = None,
        initial_history: List[Dict] = None,
        address_style: str = "您",
    ):
        self.user_id = user_id
        self.llm_service = llm_service or get_llm_service()
        if memory_manager:
            self.memory_manager = memory_manager
        else:
            from src.storage.markdown_file_manager import MarkdownFileManager
            from src.storage.memory_repository import MemoryRepository
            self.memory_manager = MemoryManager(repository=MemoryRepository(file_manager=MarkdownFileManager()))
        
        # 工具
        self.cache_tool = cache_tool or MemoryCacheTool()
        self.query_tool = query_tool or KnowledgeQueryTool()
        self.archive_tool = archive_tool or MemoryArchiveTool()
        
        # 会话状态
        self.session_state: Optional[SessionState] = None
        self.conversation_history = initial_history or []
        self.session_summary = ""
        self.is_completed = False
        
        # 继续对话Prompt
        self.resume_prompt = resume_prompt

        # 对被采访者的称呼方式（如“张爷爷”、“李叔叔”、“您”）
        self.address_style: str = address_style or "您"
        
        # 话题追踪
        self.current_topic: Optional[str] = None
        self.topic_turn_count: int = 0
        self.topic_max_turns: int = 8  # switch after 8 turns on same topic
        self.topic_history: list[str] = []  # track previous topics to avoid repeating
        
        # 问题生成器
        self.question_generator = QuestionGenerator(llm_service)
    
    async def start(self) -> str:
        """
        启动采访流程
        
        实现统一初始化逻辑，不再区分新旧用户
        如果有resume_prompt，使用它生成开场白
        否则，使用标准开场模板生成开场白
        """
        if not self.resume_prompt:
            # 没有resume_prompt时，使用标准开场模板
            self.resume_prompt = """## 角色定义
你是一位温暖、体贴的采访记者，正在帮助一位老人回忆并记录人生故事。

## 任务
请用亲切自然的语气，以晚辈聊天的方式，生成一段简短的开场白，引导老人开始讲述他的人生故事。

要求：
1. 语气亲切，像和家人聊天一样
2. 简洁明了，不要太正式
3. 邀请老人开始讲述他的人生经历
4. 字数控制在50字左右
"""
        
        # 生成开场白
        opening = await self.llm_service.invoke(
            prompt=self.resume_prompt,
            temperature=0.7
        )
        opening = opening.content
        
        # 记录对话
        self._record_turn("assistant", opening)
        
        return opening
    
    async def handle_input(
        self,
        user_input: str,
        candidate_questions: Optional[List[Dict[str, str]]] = None,
    ) -> QuestionResult:
        """
        处理用户输入

        核心流程：
        1. 记录用户回答
        2. 识别关键信息（事件/人物/时间点）
        3. 检查缓存记忆
        4. 查询知识库（如需要）
        5. 更新缓存
        6. 生成下一个问题（支持候选问题）
        """
        # 1. 记录用户回答
        self._record_turn("user", user_input)

        # 2. 识别关键信息
        key_info = await self._identify_key_information(user_input)

        # 2.5 话题追踪与换话题评估
        detected_topic = self._detect_current_topic(key_info)
        if detected_topic and detected_topic == self.current_topic:
            self.topic_turn_count += 1
        elif detected_topic and detected_topic != self.current_topic:
            # Topic changed naturally
            if self.current_topic:
                self.topic_history.append(self._stringify_topic(self.current_topic))
            self.current_topic = detected_topic
            self.topic_turn_count = 1
        else:
            # No clear topic detected, increment current
            self.topic_turn_count += 1

        should_switch = self.topic_turn_count >= self.topic_max_turns

        # 3-4. 知识库查询流程（缓存优先）
        memory_context = None
        if key_info:
            query_tags = key_info.get("tags", []) or []
            query_text = key_info.get("query_text", "") or user_input

            # 1) 先查缓存（精确 + 模糊匹配）
            cache_result = self.cache_tool.get_cache(
                session_id=self.user_id,
                query={"tags": query_tags, "query_text": query_text},
            )

            if cache_result:
                # 缓存命中，直接复用
                memory_context = cache_result
            else:
                # 2) 缓存未命中，查询知识库
                memory_context = await self.query_tool.query(
                    user_id=self.user_id,
                    query=key_info,
                    max_iterations=7,
                )

                # 3) 写入缓存供后续复用
                self.cache_tool.append_cache(
                    session_id=self.user_id,
                    content=memory_context,
                    tags=query_tags,
                )

        # 6. 生成下一个问题
        result = await self.question_generator.generate_next(
            user_input=user_input,
            memory_context=memory_context,
            conversation_history=self.conversation_history,
            candidate_questions=candidate_questions,
            should_switch_topic=should_switch,
            current_topic=self.current_topic,
            topic_turn_count=self.topic_turn_count,
            topic_history=self.topic_history,
            address_style=self.address_style,
        )

        # 如果LLM决定换话题，更新追踪状态
        if result.topic_switched and result.new_topic:
            if self.current_topic:
                self.topic_history.append(self._stringify_topic(self.current_topic))
            self.current_topic = self._stringify_topic(result.new_topic)
            self.topic_turn_count = 1

        # 记录助手回复（纯文本）
        self._record_turn("assistant", result.question)

        return result
    
    async def _identify_key_information(self, user_input: str) -> Optional[Dict]:
        """
        识别用户回答中的关键信息
        
        关键信息类型：
        - 事件：具体的事件描述
        - 人物：提到的人物姓名
        - 时间点：具体的时间节点
        - 地点：地点名称
        
        Returns:
            如果识别到关键信息，返回结构化数据
            否则返回None
        """
        identification_prompt = f"""## 任务

分析用户回答，识别其中的关键信息。

## 用户回答

{user_input}

## 输出要求

以JSON格式输出，包含以下字段：
- has_key_info: boolean，是否包含关键信息
- events: 事件列表
- persons: 人物列表
- time_points: 时间点列表
- locations: 地点列表
- query_text: 用于知识库查询的关键词组合
- tags: 用于缓存的关键词标签

如果没有关键信息，返回 {{"has_key_info": false}}

只输出JSON，不要其他内容。"""
        
        result = await self.llm_service.invoke(
            prompt=identification_prompt,
            temperature=0.3,
            response_format={"type": "json_object"},
            history=self.conversation_history  # 传递对话历史
        )
        result = result.content
        
        try:
            if isinstance(result, dict):
                parsed_result = result
            else:
                parsed_result = json.loads(result)
            
            if parsed_result.get("has_key_info"):
                return parsed_result
            return None
        except (json.JSONDecodeError, AttributeError):
            logger.error(f"Failed to parse key information result: {result}")
            return None
    
    def _detect_current_topic(self, key_info: Optional[Dict]) -> Optional[str]:
        """Extract the dominant topic from identified key information.
        
        Returns a short topic descriptor like '部队经历', '母亲', '童年学校' etc.
        """
        if not key_info:
            return None
        
        # Priority: events > persons > locations > time_points
        events = key_info.get("events", [])
        if events:
            return self._stringify_topic(events[0])
        
        persons = key_info.get("persons", [])
        if persons:
            return self._stringify_topic(persons[0])
        
        locations = key_info.get("locations", [])
        if locations:
            return self._stringify_topic(locations[0])
        
        time_points = key_info.get("time_points", [])
        if time_points:
            return self._stringify_topic(time_points[0])
        
        return None

    def _stringify_topic(self, topic) -> str:
        """Normalize model-provided topic objects into a readable short string."""
        if not topic:
            return ""
        if isinstance(topic, str):
            return topic
        if isinstance(topic, dict):
            for key in ("event", "title", "name", "topic", "description"):
                value = topic.get(key)
                if value:
                    return str(value)
        return str(topic)
    
    async def generate_ending(self) -> dict:
        """
        生成结束引导内容及下次采访建议问题。

        Returns:
            dict with keys:
                - message: 结束引导消息
                - next_questions: 下次采访建议问题列表
                - summary: 本次采访摘要
        """
        # 加载结束引导prompt
        ending_prompt = await self._load_session_end_prompt()

        # 注入变量
        prompt = ending_prompt.replace("{{session_duration}}", "")
        prompt = prompt.replace("{{total_turns}}", str(len(self.conversation_history)))
        prompt = prompt.replace("{{conversation_history}}", self._format_history())
        prompt = prompt.replace("{{elderly_title}}", self.address_style or "您")

        # 收集本次事件
        collected_events = await self._extract_collected_events()
        prompt = prompt.replace("{{collected_events}}", collected_events)

        ending_message = await self.llm_service.invoke(
            prompt=prompt,
            temperature=0.7,
            history=self.conversation_history
        )
        ending_message = ending_message.content

        # 保存会话总结
        self.session_summary = ending_message

        # --- Generate next-session questions via a second LLM call ---
        next_questions = await self._generate_next_session_questions()

        return {
            "message": ending_message,
            "next_questions": next_questions,
            "summary": ending_message,
        }

    async def _generate_next_session_questions(self) -> list:
        """生成下次采访建议问题（5-8个）。"""
        recent_conversation = self._format_recent_conversation(20)
        topic_history_str = "、".join(self.topic_history) if self.topic_history else "（无）"

        prompt = f"""基于以下采访对话记录，请生成5-8个下次采访时可以问的问题。

要求：
1. 问题应该基于本次对话中提到但未深入展开的话题线索
2. 问题应该自然延续本次采访的叙事脉络
3. 问题应该覆盖不同的话题方向（人物、事件、情感等）
4. 问题语气应该温和亲切，使用称呼: {self.address_style}
5. 优先关注被采访者主动提到但被跳过的话题

对话记录（最近20轮）:
{recent_conversation}

当前话题: {self.current_topic or '（无）'}
已探索过的话题: {topic_history_str}

请以JSON格式返回:
{{"questions": ["问题1", "问题2", ...]}}

只输出JSON，不要其他内容。"""

        try:
            result = await self.llm_service.invoke(
                prompt=prompt,
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            content = result.content
            if isinstance(content, dict):
                return self._normalize_next_questions(content.get("questions", []))
            parsed = json.loads(content)
            return self._normalize_next_questions(parsed.get("questions", []))
        except Exception as e:
            logger.error(f"Failed to generate next-session questions: {e}")
            return []

    def _normalize_next_questions(self, questions: list) -> list:
        """清理模型偶发混入的格式残留，只保留可直接展示的问题文本。"""
        import re

        cleaned = []
        for question in questions or []:
            text = str(question).strip()
            for marker in ["[/s]", "</think>", "<think>", "已严格", "```"]:
                idx = text.find(marker)
                if idx > 0:
                    text = text[:idx]
            text = re.sub(r"[\"'“”\]\}\s，。]+$", "", text).strip()
            text = re.sub(r"^[\d\.\)、\s]+", "", text).strip()
            if not text or any(token in text for token in ["JSON", "{", "}", "[/s]", "</think>"]):
                continue
            if "？" not in text and "?" not in text:
                continue
            if text not in cleaned:
                cleaned.append(text)
        return cleaned[:8]

    def _format_recent_conversation(self, n: int = 20) -> str:
        """格式化最近N轮对话历史。"""
        lines = []
        for turn in self.conversation_history[-n:]:
            role = "用户" if turn["role"] == "user" else "助手"
            lines.append(f"{role}: {turn['content']}")
        return "\n".join(lines)
    
    def _record_turn(self, role: str, content: str):
        """记录对话轮次"""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
    
    def _format_history(self) -> str:
        """格式化对话历史"""
        lines = []
        for turn in self.conversation_history[-10:]:
            role = "用户" if turn["role"] == "user" else "助手"
            lines.append(f"{role}: {turn['content']}")
        return "\n".join(lines)
    
    async def _extract_collected_events(self) -> str:
        """提取本次收集的事件"""
        # 简化实现：从对话历史中提取关键事件
        events = []
        for turn in self.conversation_history:
            if turn["role"] == "user":
                # 简单的关键词匹配
                if any(kw in turn["content"] for kw in ["那年", "那时候", "记得", "有一次"]):
                    events.append(turn["content"][:50] + "...")
        return "\n".join(events[:5])  # 最多5个
    
    async def _load_session_end_prompt(self) -> str:
        """加载结束引导Prompt"""
        from pathlib import Path
        prompt_path = Path(__file__).resolve().parent.parent.parent / "Prompts" / "SessionEndGuide-Prompt.md"
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # 提取markdown中的代码块内容
            start_idx = content.find("```") + 3
            end_idx = content.find("```", start_idx)
            if start_idx > 3 and end_idx > start_idx:
                return content[start_idx:end_idx].strip()
            return content
        except Exception as e:
            logger.error(f"Failed to load session end prompt: {e}")
            # 返回默认模板
            return """## 角色定义

你是一位温暖、体贴的采访记者。

## 输入信息

【会话时长】{{session_duration}} 分钟
【总对话轮次】{{total_turns}} 轮
【对话历史】{{conversation_history}}
【本次收集的事件】{{collected_events}}

## 输出要求

生成结束引导内容，包含：
1. 温和的结束提示
2. 本次对话亮点总结
3. 下次话题预告
4. 温暖的结束语"""
