from typing import Optional, Dict, Any, List
from datetime import datetime
import logging
import json

from src.services.llm_service import LLMService, get_llm_service
from src.services.memory_manager import MemoryManager
from src.services.question_generator import QuestionGenerator
from src.tools import MemoryCacheTool, KnowledgeQueryTool, MemoryArchiveTool
from src.models import SessionState, ConversationTurn
from src.storage.memory_repository import MemoryRepository

logger = logging.getLogger(__name__)


class InterviewAgent:
    """
    主体采访Agent
    
    职责：
    - 时间驱动的采访流程
    - 问题生成与对话引导
    - 知识库查询与缓存管理
    - 关键信息识别与追踪
    
    使用Prompt：QuestionGenerator-Prompt.md
    
    时间规则：
    - 标准时长：15分钟
    - 含初始化：5分钟
    - 12分钟时触发时间警告
    
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
        duration_minutes: int = 15,
        resume_prompt: str = None,
        initial_history: List[Dict] = None
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
        
        # 时间控制
        self.duration_minutes = duration_minutes
        self.warning_threshold = 0.8  # 80%时触发警告
        self.start_time = datetime.now()
        
        # 会话状态
        self.session_state: Optional[SessionState] = None
        self.conversation_history = initial_history or []
        self.session_summary = ""
        self.is_completed = False
        
        # 继续对话Prompt
        self.resume_prompt = resume_prompt
        
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
    
    async def handle_input(self, user_input: str) -> str:
        """
        处理用户输入
        
        核心流程：
        1. 记录用户回答
        2. 识别关键信息（事件/人物/时间点）
        3. 检查缓存记忆
        4. 查询知识库（如需要）
        5. 更新缓存
        6. 生成下一个问题
        7. 检查时间限制
        """
        # 1. 记录用户回答
        self._record_turn("user", user_input)
        
        # 2. 识别关键信息
        key_info = await self._identify_key_information(user_input)
        
        # 3-4. 知识库查询流程
        memory_context = None
        if key_info:
            # 检查缓存
            cached_content = await self.cache_tool.get_cache(
                session_id=self.user_id,
                query={"tags": key_info.get("tags", [])}
            )
            
            if cached_content:
                # 缓存命中
                memory_context = cached_content
            else:
                # 缓存未命中，查询知识库
                knowledge_result = await self.query_tool.query(
                    user_id=self.user_id,
                    query=key_info,
                    max_iterations=3
                )
                
                # 5. 更新缓存
                await self.cache_tool.append_cache(
                    session_id=self.user_id,
                    content=knowledge_result,
                    tags=key_info.get("tags", [])
                )
                
                memory_context = knowledge_result
        
        # 6. 生成下一个问题
        next_question = await self.question_generator.generate_next(
            user_input=user_input,
            memory_context=memory_context,
            conversation_history=self.conversation_history
        )
        
        # 7. 检查时间限制
        elapsed_ratio = self._get_elapsed_ratio()
        
        if elapsed_ratio >= 1.0:
            # 超时，标记完成
            self.is_completed = True
            return next_question  # 返回最后一个问题，等待回答后再结束
        elif elapsed_ratio >= self.warning_threshold:
            # 接近超时，在问题中加入时间提示
            next_question = self._add_time_warning(next_question)
        
        # 记录助手回复
        self._record_turn("assistant", next_question)
        
        return next_question
    
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
    
    async def generate_ending(self) -> str:
        """
        生成结束引导内容
        
        使用SessionEndGuide-Prompt.md
        """
        # 加载结束引导prompt
        ending_prompt = await self._load_session_end_prompt()
        
        # 注入变量
        prompt = ending_prompt.replace("{{session_duration}}", str(self.duration_minutes))
        prompt = prompt.replace("{{total_turns}}", str(len(self.conversation_history)))
        prompt = prompt.replace("{{conversation_history}}", self._format_history())
        
        # 收集本次事件
        collected_events = await self._extract_collected_events()
        prompt = prompt.replace("{{collected_events}}", collected_events)
        
        ending_message = await self.llm_service.invoke(
            prompt=prompt,
            temperature=0.7,
            history=self.conversation_history  # 传递完整对话历史
        )
        ending_message = ending_message.content
        
        # 保存会话总结
        self.session_summary = ending_message
        
        return ending_message
    
    def _get_elapsed_ratio(self) -> float:
        """获取已用时长比例"""
        elapsed = self._get_elapsed_minutes()
        return elapsed / self.duration_minutes
    
    def _get_elapsed_minutes(self) -> float:
        """获取已用时长"""
        elapsed = datetime.now() - self.start_time
        return elapsed.total_seconds() / 60
    
    def _add_time_warning(self, question: str) -> str:
        """在问题中加入时间提示"""
        return f"{question}\n\n（不知不觉聊了挺久的，我们再聊最后一个话题吧）"
    
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
        try:
            with open("/Users/yikaiwang/Documents/trae_projects/zizhuan/Prompts/SessionEndGuide-Prompt.md", 'r', encoding='utf-8') as f:
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