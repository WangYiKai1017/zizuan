from typing import Optional, Dict, Any, List
from datetime import datetime
import logging
import json
import os
import re

from src.services.llm_service import LLMService, get_llm_service
from src.services.memory_manager import MemoryManager
from src.services.observability import observe_step
from src.storage.memory_repository import MemoryRepository

logger = logging.getLogger(__name__)


class ProfileCollectionAgent:
    """
    用户初始化Agent
    
    职责：
    - 收集用户基础信息
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
    REQUIRED_FIELDS = [
        "name",
        "age",
        "gender",
        "occupation",
        "family_status",
        "living_arrangement",
    ]
    
    def __init__(
        self,
        user_id: str,
        llm_service: LLMService = None,
        memory_manager: MemoryManager = None,
        max_duration_minutes: int = 5,
        initial_info: Optional[Dict[str, Any]] = None,
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
        self.max_duration_minutes = max_duration_minutes
        self.address_style = address_style or "您"
        
        # 会话状态
        self.start_time = datetime.now()
        self.conversation_history: List[Dict] = []
        self.collected_info: Dict[str, Any] = self._normalize_fields(initial_info or {})
        self.is_completed = False
        
        # 必填字段
        self.required_fields = list(self.REQUIRED_FIELDS)
        
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
                "profile_welcome": "你叫「线团」，是一位温暖、友好的采访助手，正在帮助一位老人开始记录人生故事。\n请用亲切自然的语气打招呼，并询问老人的姓名。像晚辈聊天一样，不要太正式。",
                "profile_collection": "## 已收集信息\n{{collected_info}}\n\n## 对话历史\n{{conversation_history}}\n\n## 任务\n根据已收集的信息，选择一个合适的字段继续询问。\n使用自然的对话语气，不要像填表一样提问。\n只输出JSON。",
                "profile_extraction": "## 用户输入\n{{user_input}}\n\n## 已收集信息\n{{collected_info}}\n\n## 任务\n从用户输入中提取结构化信息，以JSON格式输出。\n只提取明确提到的信息，不要推断。"
            }
    
    def _extract_section(self, content: str, start_marker: str, end_marker: str) -> str:
        """从markdown文件中提取指定部分"""
        start_idx = content.find(start_marker)
        if start_idx == -1:
            return ""
        end_idx = content.find(end_marker, start_idx)
        if end_idx == -1:
            end_idx = len(content)

        section = content[start_idx:end_idx].strip()
        lines = section.splitlines()

        # Prompt sections are wrapped in ```markdown blocks, but also contain
        # nested ```json examples. Strip only the outer wrapper.
        first_fence = next(
            (i for i, line in enumerate(lines) if line.strip().startswith("```")),
            None,
        )
        if first_fence is not None:
            lines = lines[first_fence + 1:]
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip() == "```":
                    del lines[i]
                    break

        return "\n".join(lines).strip()
    
    async def start(self) -> str:
        """启动初始化流程"""
        if self.collected_info:
            decision = self._observe_profile_phase_decision(trigger="start")
            if decision["is_complete"]:
                self.is_completed = True
                message = await self._generate_completion_message()
            else:
                message = await self._generate_next_question()
        else:
            # 加载profile_welcome prompt
            welcome_prompt = self.prompt_templates.get("profile_welcome", "")
            
            # 注入变量
            prompt = welcome_prompt.replace("{{elderly_title}}", self.address_style)
            prompt = prompt.replace("{{collection_state}}", "INIT_PROFILE")
            
            welcome_message = await self.llm_service.invoke(
                prompt=prompt,
                temperature=0.7,
                trace_node="profile.start",
            )
            welcome_message = welcome_message.content
            
            # 解析JSON响应
            welcome_data = self._parse_json_response(welcome_message)
            message = welcome_data.get("message", welcome_message) if welcome_data else welcome_message
        
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
        self.collected_info.update(self._normalize_fields(extracted))
        
        # 检查结束条件
        decision = self._observe_profile_phase_decision(trigger="after_extract")
        if decision["is_complete"]:
            self.is_completed = True
            completion_message = await self._generate_completion_message()
            self.conversation_history.append({
                "role": "assistant",
                "content": completion_message,
                "timestamp": datetime.now().isoformat()
            })
            return completion_message
        
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
        question_bank = {
            "name": {"question": "请问您怎么称呼？", "field": "name"},
            "age": {"question": "请问您今年高寿了？", "field": "age"},
            "occupation": {"question": "您以前是做什么工作的？", "field": "occupation"},
            "birth_place": {"question": "您是在哪儿出生的？", "field": "birth_place"},
            "family_status": {"question": "您的家庭状况是怎样的？", "field": "family_status"},
            "living_arrangement": {"question": "您现在是和家人一起住，还是独居？", "field": "living_arrangement"},
            "important_person": {"question": "在您的生命中，有没有对您影响特别大的人？", "field": "important_person"},
        }
        prompt = extraction_prompt.replace("{{user_input}}", user_input)
        prompt = prompt.replace("{{question_bank}}", json.dumps(question_bank, ensure_ascii=False, indent=2))
        prompt = prompt.replace("{{already_collected}}", json.dumps(self.collected_info, ensure_ascii=False))
        prompt = prompt.replace("{{collected_info}}", json.dumps(self.collected_info, ensure_ascii=False))
        
        # 确保prompt包含"json"字样以满足API要求
        prompt += "\n\n请以JSON格式输出结果，包含fields字段。"
        fields: Dict[str, Any] = {}
        
        # 解析结果
        try:
            result = await self.llm_service.invoke(
                prompt=prompt,
                temperature=0.3,
                response_format={"type": "json_object"},
                history=self.conversation_history,  # 传递对话历史
                trace_node="profile.extract_info",
            )
            result = result.content

            if isinstance(result, dict):
                fields = result.get("fields", {})
            else:
                result_dict = self._parse_json_response(result) or {}
                fields = result_dict.get("fields", {})
            
            # 确保返回的是字典
            if isinstance(fields, dict):
                pass
            elif isinstance(fields, (list, tuple)):
                # 如果是列表或元组，尝试将其转换为字典
                # 过滤掉长度不为2的元素
                valid_items = [item for item in fields if isinstance(item, (list, tuple)) and len(item) == 2]
                fields = dict(valid_items)
            else:
                logger.warning(f"Unexpected fields type: {type(fields)}, returning empty dict")
                fields = {}
                
        except (json.JSONDecodeError, AttributeError) as e:
            logger.error(f"Failed to parse extraction result: {result}, error: {e}")
            fields = {}
        except Exception as e:
            logger.error(f"Profile extraction LLM call failed: {e}")
            fields = {}

        normalized = self._normalize_fields(fields)
        fallback_fields = self._fallback_extract_info(user_input)
        for key, value in fallback_fields.items():
            if key not in normalized and not self.collected_info.get(key):
                normalized[key] = value
        return {
            key: value for key, value in normalized.items()
            if not self.collected_info.get(key)
        }

    def _parse_json_response(self, content: Any) -> Optional[Dict[str, Any]]:
        """兼容裸 JSON 和 fenced code block JSON。"""
        if isinstance(content, dict):
            return content
        if not isinstance(content, str):
            return None

        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json|markdown)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text).strip()

        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
        return None

    def _stringify_field(self, value: Any) -> str:
        if isinstance(value, list):
            return "、".join(str(item) for item in value if item)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _normalize_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """规范化画像字段名和值，兼容 LLM 返回的常见别名。"""
        if not isinstance(fields, dict):
            return {}

        aliases = {
            "姓名": "name",
            "名字": "name",
            "高寿": "age",
            "年龄": "age",
            "性别": "gender",
            "出生日期": "birth_date",
            "出生年份": "birth_year",
            "职业": "occupation",
            "工作": "occupation",
            "家庭": "family_status",
            "家庭状况": "family_status",
            "居住": "living_arrangement",
            "居住情况": "living_arrangement",
            "居住安排": "living_arrangement",
            "children": "children_count",
            "微信ID": "wechat_id",
            "wechat_id": "wechat_id",
        }

        normalized: Dict[str, Any] = {}
        for key, value in fields.items():
            canonical = aliases.get(str(key), str(key))
            if value is None or value == "":
                continue
            normalized[canonical] = self._stringify_field(value)
        return normalized

    def _fallback_extract_info(self, user_input: str) -> Dict[str, Any]:
        """在 LLM 漏抽时保守补充明确字段；不覆盖 LLM 或已收集字段。"""
        text = user_input.strip()
        fields: Dict[str, Any] = {}

        name_match = re.search(r"(?:我叫|姓名[=:：]?|名字[=:：]?|name[=:：]?)([\u4e00-\u9fa5]{2,6})", text, re.IGNORECASE)
        if name_match:
            fields["name"] = name_match.group(1)

        age_match = re.search(r"(?:今年|年龄[=:：]?|age[=:：]?)?\s*(\d{1,3})\s*岁", text, re.IGNORECASE)
        if age_match:
            fields["age"] = str(int(age_match.group(1)))

        occupation_match = re.search(
            r"(?:我是|我以前是|退休前是|原来是|职业[是=:：]?|工作[是=:：]?|做(?:过)?|从事)([^。；;\n，,]+)",
            text,
            re.IGNORECASE,
        )
        if occupation_match:
            occupation = occupation_match.group(1).strip(" 啊呀呢的，,；;")
            if self._looks_like_occupation(occupation):
                fields["occupation"] = occupation

        family_match = re.search(
            r"([^。；;\n]*(?:老伴|妻子|丈夫|老婆|老公|儿子|女儿|孩子|孙子|孙女|外孙|外孙女)[^。；;\n]*)",
            text,
        )
        if family_match:
            family = family_match.group(1).strip(" ，,；;")
            if family:
                fields["family_status"] = family

        if re.search(r"(?:独居|自己住|一个人住)", text):
            fields["living_arrangement"] = "独居"
        else:
            living_match = re.search(r"(?:和|跟)([^。；;\n，,]{1,20})(?:一起)?住", text)
            if living_match:
                living_with = living_match.group(1).strip(" ，,；;")
                if living_with:
                    fields["living_arrangement"] = f"和{living_with}一起住"

        return fields

    def _looks_like_occupation(self, value: str) -> bool:
        if not value or len(value) > 20:
            return False
        occupation_keywords = [
            "程序员", "工程师", "老师", "教师", "医生", "护士", "司机", "工人",
            "农民", "会计", "出纳", "厨师", "军人", "干部", "公务员", "警察",
            "营业员", "售货员", "技术员", "设计师", "律师", "记者", "编辑",
            "老板", "个体户", "做生意", "退休",
        ]
        return any(keyword in value for keyword in occupation_keywords)

    def _missing_required_fields(self) -> List[str]:
        return [
            field for field in self.required_fields
            if field not in self.collected_info or not self.collected_info[field]
        ]

    def _profile_phase_decision(self) -> Dict[str, Any]:
        missing_required = self._missing_required_fields()
        elapsed = self._get_elapsed_minutes()
        required_complete = not missing_required
        time_exceeded = elapsed >= self.max_duration_minutes
        is_complete = required_complete or time_exceeded
        if required_complete:
            reason = "all_required_fields_complete"
        elif time_exceeded:
            reason = "max_duration_exceeded"
        else:
            reason = "missing_required_fields"
        return {
            "is_complete": is_complete,
            "next_phase": "interview" if is_complete else "profile",
            "reason": reason,
            "missing_required_fields": missing_required,
            "collected_fields": sorted(self.collected_info.keys()),
            "elapsed_minutes": round(elapsed, 3),
        }

    def _observe_profile_phase_decision(self, trigger: str) -> Dict[str, Any]:
        decision = self._profile_phase_decision()
        with observe_step(
            "profile.phase_decision",
            as_type="tool",
            input={
                "trigger": trigger,
                "required_fields": self.required_fields,
                "collected_info": self.collected_info,
            },
            metadata={
                "trigger": trigger,
                "next_phase": decision["next_phase"],
                "reason": decision["reason"],
                "missing_required_fields": decision["missing_required_fields"],
            },
        ) as observation:
            if observation is not None:
                observation.update(output=decision)
        return decision

    def _should_complete(self) -> bool:
        """判断是否应该结束初始化"""
        return bool(self._profile_phase_decision()["is_complete"])
    
    async def _generate_next_question(self) -> str:
        """
        生成下一个收集问题
        
        根据已收集信息，选择下一个合适的字段询问
        """
        # 加载profile_collection prompt
        collection_prompt = self.prompt_templates.get("profile_collection", "")

        missing_required = self._missing_required_fields()
        optional_fields = [
            "birth_year", "birth_place", "children_count",
            "health_status", "important_person", "favorite_memory",
        ]
        current_state = "READY" if not missing_required else "COLLECT_BASIC"
        last_user_input = ""
        for turn in reversed(self.conversation_history):
            if turn.get("role") == "user":
                last_user_input = turn.get("content", "")
                break
        
        # 注入上下文
        prompt = collection_prompt.replace("{{current_state}}", current_state)
        prompt = prompt.replace("{{collected_fields}}", json.dumps(self.collected_info, ensure_ascii=False))
        prompt = prompt.replace("{{required_fields}}", json.dumps(missing_required, ensure_ascii=False))
        prompt = prompt.replace("{{optional_fields}}", json.dumps(optional_fields, ensure_ascii=False))
        prompt = prompt.replace("{{last_user_input}}", last_user_input)
        prompt = prompt.replace("{{elderly_title}}", self.address_style)
        prompt = prompt.replace("{{collected_info}}", json.dumps(self.collected_info, ensure_ascii=False))
        prompt = prompt.replace("{{conversation_history}}", self._format_history())
        
        question = await self.llm_service.invoke(
            prompt=prompt,
            temperature=0.7,
            response_format={"type": "json_object"},
            trace_node="profile.generate_next_question",
            trace_metadata={
                "current_state": current_state,
                "missing_required_fields": missing_required,
                "expected_output": "profile_question_json",
                "conversation_history_turns": min(len(self.conversation_history), 6),
            },
        )
        question = question.content
        
        # 解析JSON响应
        question_data = self._parse_json_response(question)
        if question_data and question_data.get("question"):
            selected_field = (
                question_data.get("field")
                or question_data.get("next_field")
                or question_data.get("target_field")
            )
            allowed_fields = set(missing_required + optional_fields)
            if not missing_required or selected_field in allowed_fields:
                return question_data["question"]
            logger.warning(
                "profile.generate_next_question selected invalid field %s; missing_required=%s",
                selected_field,
                missing_required,
            )

        logger.warning("profile.generate_next_question returned invalid JSON question: %s", question)
        return self._fallback_next_question(missing_required)

    def _fallback_next_question(self, missing_required: List[str]) -> str:
        fallback_questions = {
            "name": "请问您怎么称呼？",
            "age": "请问您今年高寿了？",
            "gender": "方便问一下您的性别吗？",
            "occupation": "您以前主要是做什么工作的？",
            "family_status": "您方便说说家里的情况吗？比如现在家里有哪些亲人常联系。",
            "living_arrangement": "您现在是自己住，还是和家人一起住呢？",
        }
        next_field = missing_required[0] if missing_required else None
        if next_field is None:
            return "您愿意再多说一点吗？"
        return fallback_questions.get(next_field, "您愿意再多说一点吗？")
    
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
