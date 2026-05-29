from typing import Optional, Dict, Any, List
from datetime import datetime
import logging
import json
import os

from src.services.llm_service import LLMService, get_llm_service
from src.services.memory_manager import MemoryManager
from src.storage.memory_repository import MemoryRepository

logger = logging.getLogger(__name__)


class ProfileCollectionAgent:
    """
    用户初始化Agent
    
    职责：
    - 收集用户基础信息（14个字段）
    - 渐进式提问，自然对话
    - 从用户回答中提取信息
    
    使用Prompt：ProfileCollection-Prompt.md
    
    结束条件：
    1. 收集到足够信息（必填字段完成）
    2. 对话超过5分钟
    
    输出：
    - 将对话记录传给MemoryOrganizer
    - 生成用户基础知识库
    """
    
    def __init__(
        self,
        user_id: str,
        llm_service: LLMService = None,
        memory_manager: MemoryManager = None,
        max_duration_minutes: int = 5
    ):
        self.user_id = user_id
        self.llm_service = llm_service or get_llm_service()
        if memory_manager:
            self.memory_manager = memory_manager
        else:
            from src.storage.markdown_file_manager import MarkdownFileManager
            from src.storage.memory_repository import MemoryRepository
            self.memory_manager = MemoryManager(repository=MemoryRepository(file_manager=MarkdownFileManager()))
        self.max_duration_minutes = max_duration_minutes
        
        # 会话状态
        self.start_time = datetime.now()
        self.conversation_history: List[Dict] = []
        self.collected_info: Dict[str, Any] = {}
        self.is_completed = False
        
        # 必填字段
        self.required_fields = ['name', 'age', 'occupation', 'family_status', 
                                'living_arrangement', 'story_expectation']
        
        # 加载prompt模板
        self.prompt_templates = self._load_prompt_templates()
    
    def _load_prompt_templates(self) -> Dict[str, str]:
        """从文件加载prompt模板"""
        from pathlib import Path
        prompt_path = Path(__file__).resolve().parent.parent.parent / "Prompts" / "ProfileCollection-Prompt.md"
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 提取不同的模板部分
            templates = {
                "profile_welcome": self._extract_section(content, "二、首次问候 Prompt", "三、信息提取 Prompt"),
                "profile_extraction": self._extract_section(content, "三、信息提取 Prompt", "四、问题生成 Prompt"),
                "profile_collection": self._extract_section(content, "四、问题生成 Prompt", "五、技术集成说明")
            }
            return templates
        except Exception as e:
            logger.error(f"Failed to load prompt templates: {e}")
            # 返回默认模板
            return {
                "profile_welcome": "你是一位温暖、友好的采访助手，正在帮助一位老人开始记录人生故事。\n请用亲切自然的语气打招呼，并询问老人的姓名。像晚辈聊天一样，不要太正式。",
                "profile_collection": "## 已收集信息\n{{collected_info}}\n\n## 对话历史\n{{conversation_history}}\n\n## 任务\n根据已收集的信息，选择一个合适的字段继续询问。\n使用自然的对话语气，不要像填表一样提问。",
                "profile_extraction": "## 用户输入\n{{user_input}}\n\n## 已收集信息\n{{collected_info}}\n\n## 任务\n从用户输入中提取结构化信息，以JSON格式输出。\n只提取明确提到的信息，不要推断。"
            }
    
    def _extract_section(self, content: str, start_marker: str, end_marker: str) -> str:
        """从markdown文件中提取指定部分"""
        start_idx = content.find(start_marker)
        if start_idx == -1:
            return ""
        start_idx = content.find("```", start_idx) + 3
        end_idx = content.find("```", start_idx)
        if end_idx == -1:
            return ""
        return content[start_idx:end_idx].strip()
    
    async def start(self) -> str:
        """启动初始化流程"""
        # 加载profile_welcome prompt
        welcome_prompt = self.prompt_templates.get("profile_welcome", "")
        
        # 注入变量
        prompt = welcome_prompt.replace("{{elderly_title}}", "老人家")
        prompt = prompt.replace("{{collection_state}}", "INIT_PROFILE")
        
        welcome_message = await self.llm_service.invoke(
            prompt=prompt,
            temperature=0.7
        )
        welcome_message = welcome_message.content
        
        # 解析JSON响应
        try:
            welcome_data = json.loads(welcome_message)
            message = welcome_data.get("message", welcome_message)
        except json.JSONDecodeError:
            # 如果不是JSON格式，直接使用
            message = welcome_message
        
        # 记录对话
        self.conversation_history.append({
            "role": "assistant",
            "content": message,
            "timestamp": datetime.now().isoformat()
        })
        
        return message
    
    async def handle_input(self, user_input: str) -> str:
        """
        处理用户输入
        
        流程：
        1. 记录用户输入
        2. 从输入中提取信息
        3. 检查是否完成收集
        4. 生成下一个问题
        """
        # 记录用户输入
        self.conversation_history.append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat()
        })
        
        # 提取信息
        extracted = await self._extract_info(user_input)
        self.collected_info.update(extracted)
        
        # 检查结束条件
        if self._should_complete():
            self.is_completed = True
            return await self._generate_completion_message()
        
        # 生成下一个问题
        next_question = await self._generate_next_question()
        
        # 记录助手回复
        self.conversation_history.append({
            "role": "assistant",
            "content": next_question,
            "timestamp": datetime.now().isoformat()
        })
        
        return next_question
    
    async def _extract_info(self, user_input: str) -> Dict[str, Any]:
        """
        从用户输入中提取信息
        
        使用profile_extraction prompt
        """
        extraction_prompt = self.prompt_templates.get("profile_extraction", "")
        
        # 注入变量
        prompt = extraction_prompt.replace("{{user_input}}", user_input)
        prompt = prompt.replace("{{collected_info}}", str(self.collected_info))
        
        # 确保prompt包含"json"字样以满足API要求
        prompt += "\n\n请以JSON格式输出结果，包含fields字段。"
        result = await self.llm_service.invoke(
            prompt=prompt,
            temperature=0.3,
            response_format={"type": "json_object"},
            history=self.conversation_history  # 传递对话历史
        )
        result = result.content
        
        # 解析结果
        try:
            if isinstance(result, dict):
                fields = result.get("fields", {})
            else:
                result_dict = json.loads(result)
                fields = result_dict.get("fields", {})
            
            # 确保返回的是字典
            if isinstance(fields, dict):
                return fields
            elif isinstance(fields, (list, tuple)):
                # 如果是列表或元组，尝试将其转换为字典
                # 过滤掉长度不为2的元素
                valid_items = [item for item in fields if isinstance(item, (list, tuple)) and len(item) == 2]
                return dict(valid_items)
            else:
                logger.warning(f"Unexpected fields type: {type(fields)}, returning empty dict")
                return {}
                
        except (json.JSONDecodeError, AttributeError) as e:
            logger.error(f"Failed to parse extraction result: {result}, error: {e}")
            return {}
    
    def _should_complete(self) -> bool:
        """判断是否应该结束初始化"""
        # 检查必填字段
        required_complete = all(
            field in self.collected_info and self.collected_info[field]
            for field in self.required_fields
        )
        
        # 检查时间限制
        elapsed = self._get_elapsed_minutes()
        time_exceeded = elapsed >= self.max_duration_minutes
        
        return required_complete or time_exceeded
    
    async def _generate_next_question(self) -> str:
        """
        生成下一个收集问题
        
        根据已收集信息，选择下一个合适的字段询问
        """
        # 加载profile_collection prompt
        collection_prompt = self.prompt_templates.get("profile_collection", "")
        
        # 注入上下文
        prompt = collection_prompt.replace("{{collected_info}}", str(self.collected_info))
        prompt = prompt.replace("{{conversation_history}}", self._format_history())
        
        question = await self.llm_service.invoke(
            prompt=prompt,
            temperature=0.7,
            history=self.conversation_history  # 传递对话历史
        )
        question = question.content
        
        # 解析JSON响应
        try:
            question_data = json.loads(question)
            return question_data.get("question", question)
        except json.JSONDecodeError:
            # 如果不是JSON格式，直接使用
            return question
    
    async def _generate_completion_message(self) -> str:
        """生成初始化完成的消息"""
        return f"好的，我已经了解了您的基本情况。接下来我们可以开始聊聊您的人生故事了，您准备好了吗？"
    
    def _get_elapsed_minutes(self) -> float:
        """获取已用时长"""
        elapsed = datetime.now() - self.start_time
        return elapsed.total_seconds() / 60
    
    def get_conversation_history(self) -> List[Dict]:
        """获取对话记录"""
        return self.conversation_history
    
    def _format_history(self) -> str:
        """格式化对话历史"""
        lines = []
        for turn in self.conversation_history[-6:]:  # 只取最近6轮
            role = "用户" if turn["role"] == "user" else "助手"
            lines.append(f"{role}: {turn['content']}")
        return "\n".join(lines)