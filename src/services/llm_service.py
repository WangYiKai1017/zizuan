from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TypeVar, Generic
from pydantic import BaseModel
import asyncio
from datetime import datetime
import logging
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from src.config.llm_config import LLMConfig
from src.prompts.base import PromptTemplate

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class LLMCallResult(BaseModel):
    """大模型调用结果"""
    success: bool
    content: str = ""
    raw_response: Any = None
    token_usage: Dict[str, int] = {}
    latency_ms: int = 0
    error: Optional[str] = None
    model_name: str = ""
    timestamp: datetime = datetime.now()


class LLMService:
    """
    大模型调用统一入口
    
    职责：
    - 统一管理所有大模型调用
    - 封装LangChain调用逻辑
    - 提供Prompt模板管理
    - 统一错误处理和重试
    - 记录调用日志和统计
    
    使用场景：
    - QuestionGenerator 生成问题
    - EmotionDetector 识别情绪
    - ContentSummarizer 归纳内容
    - KnowledgeBaseQuerier 提取实体（可选）
    
    示例用法：
    ```python
    llm_service = LLMService(config)
    
    # 简单调用
    result = await llm_service.invoke("你好")
    
    # 带Prompt模板调用
    result = await llm_service.invoke_with_template(
        template="question_generation",
        variables={"user_input": "...", "state": "..."}
    )
    
    # 结构化输出
    emotion_result = await llm_service.invoke_structured(
        template="emotion_detection",
        variables={"user_input": "..."},
        output_model=EmotionResult
    )
    ```
    """
    
    def __init__(self, config: LLMConfig):
        """
        初始化LLMService
        
        Args:
            config: LLM配置对象
        """
        self.config = config
        self._model: Optional[BaseChatModel] = None
        self._prompt_templates: Dict[str, PromptTemplate] = {}
        self._call_history: List[LLMCallResult] = []
        self._total_tokens = 0
        
        # 初始化模型
        self._init_model()
        
        # 加载Prompt模板
        self._load_prompt_templates()
    
    def _init_model(self) -> None:
        """初始化LangChain模型"""
        model_config = self.config
        
        if model_config.provider in ["openai", "qwen"]:
            # Qwen兼容OpenAI的API格式
            self._model = ChatOpenAI(
                model=model_config.model_name,
                temperature=model_config.temperature,
                max_tokens=model_config.max_tokens,
                api_key=model_config.api_key,
                base_url=model_config.base_url,
            )
        elif model_config.provider == "anthropic":
            # 动态导入，只在需要时加载
            from langchain_anthropic import ChatAnthropic
            self._model = ChatAnthropic(
                model=model_config.model_name,
                temperature=model_config.temperature,
                max_tokens=model_config.max_tokens,
                api_key=model_config.api_key,
            )
        else:
            raise ValueError(f"Unsupported provider: {model_config.provider}")
        
        logger.info(f"Initialized LLM model: {model_config.provider}/{model_config.model_name}")
    
    def _load_prompt_templates(self) -> None:
        """加载所有Prompt模板（从外部Markdown文件和Python模块）"""
        import os
        import re
        from src.prompts.base import PromptTemplate
        
        # 从Python模块加载模板
        try:
            from src.prompts import TEMPLATES as PYTHON_TEMPLATES
            for name, template in PYTHON_TEMPLATES.items():
                self._prompt_templates[name] = template
                logger.info(f"Loaded prompt template from Python module: {name}")
        except ImportError as e:
            logger.warning(f"Failed to load Python prompt templates: {e}")
        
        # 外部Prompt模板目录
        prompts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "src", "prompts")
        
        if not os.path.exists(prompts_dir):
            logger.warning(f"Prompts directory not found: {prompts_dir}")
            return
        
        # 遍历目录下的所有Markdown文件
        for filename in os.listdir(prompts_dir):
            if filename.endswith(".md"):
                file_path = os.path.join(prompts_dir, filename)
                try:
                    template = self._parse_prompt_from_markdown(file_path)
                    if template:
                        self._prompt_templates[template.name] = template
                        logger.info(f"Loaded prompt template from file: {template.name}")
                except Exception as e:
                    logger.error(f"Failed to load template {filename}: {e}")
        
        logger.info(f"Loaded {len(self._prompt_templates)} prompt templates from {prompts_dir}")
        print(f"Loaded {len(self._prompt_templates)} prompt templates from {prompts_dir}")
    
    def _parse_prompt_from_markdown(self, file_path: str) -> Optional[PromptTemplate]:
        """从Markdown文件解析Prompt模板"""
        import os
        import re
        from src.prompts.base import PromptTemplate
        
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 提取模板名称
        name_match = re.search(r'模板名称：`([^`]+)`', content)
        if not name_match:
            return None
        template_name = name_match.group(1)
        
        # 提取模板内容（在```之间的内容）
        template_content_match = re.search(r'```(?:[\w]+)?\n(.*?)\n```', content, re.DOTALL)
        if not template_content_match:
            return None
        template_content = template_content_match.group(1).strip()
        
        # 提取变量信息
        variables = {}
        variables_section = re.search(r'## 二、动态变量说明\n(.*?)(?=##|$)', content, re.DOTALL)
        if variables_section:
            # 提取表格中的变量
            table_content = re.search(r'\|.*\|.*\|.*\|.*\|.*\n(?:\|.*\|.*\|.*\|.*\|.*\n)+', variables_section.group(1))
            if table_content:
                lines = table_content.group(0).split('\n')[1:-1]  # 跳过表头和空行
                for line in lines:
                    parts = [p.strip() for p in line.split('|') if p.strip()]
                    if len(parts) >= 2:
                        var_name = parts[0]
                        # 去除反引号
                        var_name = var_name.strip('`')
                        # 去除{}或${}
                        if var_name.startswith('${') and var_name.endswith('}'):
                            var_name = var_name[2:-1]
                        elif var_name.startswith('{') and var_name.endswith('}'):
                            var_name = var_name[1:-1]
                        # 如果变量以$开头，去除$符号
                        if var_name.startswith('$'):
                            var_name = var_name[1:]
                        var_desc = parts[-1]
                        variables[var_name] = var_desc
        
        # 创建PromptTemplate对象
        return PromptTemplate(
            name=template_name,
            description=f"从文件 {os.path.basename(file_path)} 加载的模板",
            system_prompt=template_content,  # 整个模板内容作为system_prompt
            user_template="",  # 用户模板部分在实际使用时动态添加
            variables=variables
        )
    
    @property
    def model(self) -> BaseChatModel:
        """获取模型实例"""
        if self._model is None:
            raise RuntimeError("Model not initialized")
        return self._model
    
    async def invoke(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> LLMCallResult:
        """
        基础调用方法
        
        Args:
            prompt: 用户提示
            system_prompt: 系统提示（可选）
            **kwargs: 额外参数
            
        Returns:
            LLMCallResult: 调用结果
        """
        start_time = datetime.now()
        
        try:
            # 构建消息
            messages = []
            if system_prompt:
                messages.append(SystemMessage(content=system_prompt))
            messages.append(HumanMessage(content=prompt))
            
            # 调用模型（带重试）

            # raise ValueError("Not implemented")
            response = await self._invoke_with_retry(messages, **kwargs)
            
            # 记录结果
            latency = (datetime.now() - start_time).total_seconds() * 1000
            result = LLMCallResult(
                success=True,
                content=response.content,
                raw_response=response,
                token_usage=self._extract_token_usage(response),
                latency_ms=int(latency),
                model_name=self.config.model_name,
            )
            
            # 更新统计
            self._total_tokens += result.token_usage.get("total_tokens", 0)
            self._call_history.append(result)
            
            return result
            
        except Exception as e:
            logger.error(f"LLM invoke failed: {e}")
            return LLMCallResult(
                success=False,
                error=str(e),
                model_name=self.config.model_name,
            )
    
    async def invoke_with_template(
        self,
        template_name: str,
        variables: Dict[str, Any],
        **kwargs
    ) -> LLMCallResult:
        """
        使用Prompt模板调用
        
        Args:
            template_name: 模板名称
            variables: 模板变量
            **kwargs: 额外参数
            
        Returns:
            LLMCallResult: 调用结果
        """
        if template_name not in self._prompt_templates:
            raise ValueError(f"Template not found: {template_name}")
        
        template = self._prompt_templates[template_name]
        
        # 渲染Prompt
        prompt = template.render(**variables)
        
        return await self.invoke(
            prompt=prompt,
            system_prompt=template.system_prompt,
            **kwargs
        )
    
    async def invoke_structured(
        self,
        template_name: str,
        variables: Dict[str, Any],
        output_model: type[T],
        **kwargs
    ) -> tuple[Optional[T], LLMCallResult]:
        """
        结构化输出调用 - 返回Pydantic模型
        
        Args:
            template_name: 模板名称
            variables: 模板变量
            output_model: 输出模型类（Pydantic BaseModel）
            **kwargs: 额外参数
            
        Returns:
            tuple: (解析后的模型实例, 原始调用结果)
        """
        # 获取模板
        if template_name not in self._prompt_templates:
            raise ValueError(f"Template not found: {template_name}")
        
        template = self._prompt_templates[template_name]
        
        # 渲染Prompt
        template.system_prompt = template.render(**variables)
        
        # 构建结构化输出的Prompt
        structured_prompt = f"""

        请按照以下JSON格式输出：
        {output_model.model_json_schema()}

            注意：
            1. 只输出JSON，不要输出其他内容
            2. 确保JSON格式正确
            3. 所有字段都必须填写
        """
        
        # 调用模型

        result = await self.invoke(
            prompt=structured_prompt,
            system_prompt=template.system_prompt,
            **kwargs
        )
        
        if not result.success:
            return None, result
        
        # 解析JSON
        try:
            import json
            content = result.content.strip()
            
            # 尝试提取JSON（处理可能的额外文本）
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            data = json.loads(content)
            model_instance = output_model.model_validate(data)
            
            return model_instance, result
            
        except Exception as e:
            logger.error(f"Failed to parse structured output: {e}")
            result.success = False
            result.error = f"Parse error: {e}"
            return None, result
    
    async def _invoke_with_retry(
        self,
        messages: List[BaseMessage],
        max_retries: int = 3,
        **kwargs
    ) -> Any:
        """
        带重试的调用
        
        Args:
            messages: 消息列表
            max_retries: 最大重试次数
            **kwargs: 额外参数
            
        Returns:
            模型响应
        """
        last_error = None
        
        # raise ValueError("Not implemented")

        for attempt in range(max_retries):
            try:
                print(f"正在请求大模型...")
                response = await self.model.ainvoke(messages, **kwargs)
                print(f"请求完成")
                return response
            except Exception as e:
                print(f"异常 Attempt {attempt + 1} failed: {e}")
                last_error = e
                wait_time = 2 ** attempt  # 指数退避
                logger.warning(
                    f"LLM call failed (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
        
        raise last_error
    
    def _extract_token_usage(self, response: Any) -> Dict[str, int]:
        """提取Token使用量"""
        if hasattr(response, "usage_metadata"):
            return {
                "prompt_tokens": response.usage_metadata.get("input_tokens", 0),
                "completion_tokens": response.usage_metadata.get("output_tokens", 0),
                "total_tokens": response.usage_metadata.get("total_tokens", 0),
            }
        return {}
    
    def get_stats(self) -> Dict[str, Any]:
        """获取调用统计"""
        return {
            "total_calls": len(self._call_history),
            "total_tokens": self._total_tokens,
            "success_rate": sum(1 for r in self._call_history if r.success) / len(self._call_history) if self._call_history else 0,
            "avg_latency_ms": sum(r.latency_ms for r in self._call_history) / len(self._call_history) if self._call_history else 0,
        }
    
    def clear_history(self) -> None:
        """清空调用历史"""
        self._call_history.clear()
        self._total_tokens = 0


# 全局单例（可选）
_llm_service_instance: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """获取全局LLMService实例"""
    global _llm_service_instance
    if _llm_service_instance is None:
        from src.config.llm_config import get_default_config
        _llm_service_instance = LLMService(get_default_config())
    return _llm_service_instance


def init_llm_service(config: LLMConfig) -> LLMService:
    """初始化全局LLMService实例"""
    global _llm_service_instance
    _llm_service_instance = LLMService(config)
    return _llm_service_instance