from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path
import logging
import json
import re

from src.agents.guided_initial_interview_controller import GuidedInitialInterviewController
from src.services.llm_service import LLMService, get_llm_service
from src.services.memory_manager import MemoryManager
from src.services.observability import observe_step
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
        initial_history: List[Dict] = None,
        knowledge_base_root: str | Path | None = None,
        resume_context: dict | None = None,
        guided_controller: GuidedInitialInterviewController = None,
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

        self.knowledge_base_root = Path(knowledge_base_root) if knowledge_base_root else (
            Path(__file__).resolve().parent.parent.parent / "knowledge_base"
        )

        # 称呼方式（后续 Task 4 中全局清理）
        self.address_style = "您"
        # Resume 上下文（老用户回来时由 InterviewSessionAgent 传入）
        self.resume_context = resume_context or {}
        # 上次对话记录原文（避免 agent 围绕同一问题重复发问）
        self.resume_conversation_text = self.resume_context.get("conversation_text", "")

        # 话题追踪（老用户从 resume_context 恢复，新用户从零开始）
        resume_topic_history = self.resume_context.get("topic_history") or []
        resume_current_topic = self.resume_context.get("current_topic")

        self.current_topic: Optional[str] = resume_current_topic
        self.topic_turn_count: int = 0
        self.topic_max_turns: int = 8  # switch after 8 turns on same topic
        self.topic_history: list[str] = list(resume_topic_history)  # track previous topics to avoid repeating
        
        # 问题生成器
        self.question_generator = QuestionGenerator(llm_service)
        self.guided_controller = guided_controller or GuidedInitialInterviewController(
            user_id=self.user_id,
            llm_service=self.llm_service,
            knowledge_base_root=self.knowledge_base_root,
        )
    
    async def start(self) -> str:
        """
        启动采访流程

        老用户 (resume_context 存在) → LLM 生成欢迎回来的开场白
        新用户 (resume_context 不存在) → 模板开场白
        """
        guided_question = self.guided_controller.current_start_question()

        if self.resume_context and guided_question:
            # 老用户回来 → 轻量 LLM 开场白
            opening = await self._build_resume_opening(guided_question)
        elif guided_question:
            # 新用户（profile 完成后）→ 模板开场白
            opening = self.guided_controller.build_start_message()
        else:
            # 引导阶段已完成 → 通用欢迎语
            opening = "你好呀，欢迎回来！今天想从哪里接着聊呢？"

        self._record_turn("assistant", opening)
        return opening

    async def _build_resume_opening(self, guided_question: dict) -> str:
        """为老用户生成欢迎回来的开场白。

        只使用上次采访摘要 + 当前引导问题，一次 LLM 调用。
        """
        ctx = self.resume_context or {}
        summary = (ctx.get("summary") or "").strip()
        conversation_text = (ctx.get("conversation_text") or "").strip()

        guided_text = guided_question.get("question", "")
        guided_stage = guided_question.get("stage_label") or guided_question.get("stage") or ""

        # 上次对话记录段（避免重复发问）
        prev_conv_section = ""
        if conversation_text:
            prev_conv_section = f"""## 上次围绕同一问题的对话记录
以下是上次 session 中已经聊过的内容，请避免重复问同样的问题：
{conversation_text}

"""

        prompt = f"""## 角色定义
你是一位温暖、体贴的采访记者，正在帮助一位老人回忆并记录人生故事。
用户之前已经有过对话，现在需要你生成一段欢迎回来的开场白。

## 上次采访摘要
{summary[:200] or '无'}

{prev_conv_section}## 当前要继续的引导问题
- 阶段：{guided_stage}
- 问题：{guided_text}

## 内容使用规则
- "上次采访摘要"是判断上次聊了什么的最高优先级依据
- "上次对话记录"里的内容说明用户已经聊过这些细节，请不要生成重复的问题
- 如果摘要为空或过于泛泛，不要编造具体故事，只做温和欢迎
- 结尾自然引出"当前要继续的引导问题"，但不要原样重复引导问题原文

## 输出要求
1. 以"你好呀，欢迎回来"开头
2. 简要回顾上次摘要（1-2 句，不得编造）
3. 最后引出当前引导问题
4. 语气温暖、亲切，像老朋友聊天，80 字左右
5. 只输出开场白本身"""

        try:
            result = await self.llm_service.invoke(
                prompt=prompt,
                temperature=0.7,
                trace_node="start.guided_resume",
            )
            text = str(result.content).strip()
            if text:
                return text
        except Exception as e:
            logger.warning("Failed to generate resume opening: %s", e)

        return (
            f"你好呀，欢迎回来。上次聊到的内容我们都记着呢，"
            f"今天我们顺着之前的节奏慢慢接着聊：{guided_text}"
        )

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
                with observe_step(
                    "turn.kb_query",
                    as_type="tool",
                    input={"query": key_info},
                ):
                    memory_context = await self.query_tool.query(
                        user_id=self.user_id,
                        query=key_info,
                    )

                # 3) 写入缓存供后续复用
                self.cache_tool.append_cache(
                    session_id=self.user_id,
                    content=memory_context,
                    tags=query_tags,
                )

        if self.guided_controller.is_active():
            decision = await self.guided_controller.generate_next(
                user_input=user_input,
                memory_context=memory_context,
                conversation_history=self.conversation_history,
                candidate_questions=candidate_questions,
                address_style=self.address_style,
                previous_conversation_text=self.resume_conversation_text,
            )
            result = decision.result
            # 仅首轮注入，之后清空避免后续轮次重复注入
            self.resume_conversation_text = ""
        else:
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
        提取用户表达中可用于检索历史知识库的信息
        
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

分析用户当前的表达，提取适合查询其历史知识库的主题线索。

这里判断的是“是否存在可检索的具体主题”，不是“用户是否提供了新的事实”。
无论用户是在陈述、提问，还是引用已经谈过的内容，只要提到了具体人物、事件、经历、时间或地点，都应返回 has_key_info=true。

生成 query_text 时：
- 使用对话历史消解“那件事”“那个老师”等指代
- 提炼成简短、具体的历史主题，例如“北京求学经历”“语文老师鼓励作文”
- 去掉寒暄、反问等对检索无帮助的表达
- tags 使用主题中的核心人物、事件、时间和地点

只有“嗯”“好的”“继续吧”等完全没有具体主题的表达，才返回 has_key_info=false。

## 用户回答

{user_input}

## 输出要求

以JSON格式输出，包含以下字段：
- has_key_info: boolean，是否包含关键信息
- events: 事件或经历主题列表
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
            history=self.conversation_history,  # 传递对话历史
            trace_node="turn.identify_key_information",
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

        ending_result = await self.llm_service.invoke(
            prompt=prompt,
            temperature=0.7,
            history=self.conversation_history,
            response_format={"type": "json_object"},
            trace_node="ending.generate_summary",
        )

        # 解析 JSON 响应，提取 title、summary 和 message。
        title = ""
        summary = ""
        ending_message = ""
        try:
            content = ending_result.content
            if isinstance(content, dict):
                title = str(content.get("title", "")).strip()
                summary = str(content.get("summary", "")).strip()
                ending_message = str(content.get("message", "")).strip()
            else:
                parsed = json.loads(content)
                title = str(parsed.get("title", "")).strip()
                summary = str(parsed.get("summary", "")).strip()
                ending_message = str(parsed.get("message", "")).strip()
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse ending JSON, falling back to raw content: {e}")
            ending_message = ending_result.content if isinstance(ending_result.content, str) else str(ending_result.content)

        if not ending_message:
            ending_message = "今天和您聊天很愉快，谢谢您的分享！下次我们继续聊，祝您生活愉快！"

        # 保存会话事实摘要，供结构化归档和下次恢复使用。
        self.session_summary = summary

        # --- Generate next-session questions via a second LLM call ---
        next_questions = await self._generate_next_session_questions()

        return {
            "title": title,
            "message": ending_message,
            "next_questions": next_questions,
            "summary": summary,
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
                trace_node="ending.generate_next_session_questions",
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
