# 开发故事卡 - Task 2: 实现LLMService

> 任务编号：Task-002  
> 优先级：P0  
> 依赖：Task-001（数据对象）  
> 预计工时：1天

---

## 一、任务概述

实现LLMService（大模型调用服务），作为整个问答引导层Agent系统调用大模型能力的**统一入口**。所有需要大模型能力的Service对象都必须通过LLMService进行调用，禁止直接调用大模型API。

---

## 二、项目上下文

### 2.1 系统定位

本系统是「老人自传Agent系统」的**问答引导层**，负责与老人进行多轮对话，收集人生故事。系统采用Python + LangChain/LangGraph技术栈，遵循Harness范式。

### 2.2 Harness范式核心原则

```
1. Agent职责单一：每个Agent只做一件事
2. 模型统一入口：所有大模型调用通过LLMService统一管理
3. 异步并发：耗时操作异步执行，不阻塞主流程
4. 状态驱动：通过状态流转控制Agent行为
5. Prompt集中管理：所有Prompt模板集中定义，版本可控
```

### 2.3 LLMService的核心价值

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     为什么需要LLMService？                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. 统一入口：所有大模型调用通过一个对象，便于监控、限流、计费            │
│  2. 模型切换：支持在不同模型间切换（GPT/Claude/本地模型），业务无感知     │
│  3. Prompt管理：集中管理所有Prompt模板，版本可控                         │
│  4. 错误处理：统一的错误处理和重试机制                                   │
│  5. 日志追踪：统一记录调用日志，便于调试和优化                           │
│  6. 成本控制：统一的Token计数和成本统计                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

调用链路：
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ QuestionGen │     │ EmotionDet  │     │ ContentSum  │
│             │     │             │     │             │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │   LLMService    │ ← 统一入口
                  │                 │
                  │  - LangChain    │
                  │  - Prompt模板   │
                  │  - 重试机制     │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │  大模型 API     │
                  │  (GPT/Claude/...)│
                  └─────────────────┘
```

### 2.4 技术栈

- Python 3.10+
- LangChain（模型调用抽象）
- LangGraph（Agent编排，暂不在此任务）
- Pydantic（配置验证）
- asyncio（异步调用）

---

## 三、详细设计

### 3.1 目录结构

```
src/
├── services/
│   ├── __init__.py
│   └── llm_service.py          # LLMService主文件
├── prompts/
│   ├── __init__.py
│   ├── base.py                 # 基础Prompt模板
│   ├── question_prompts.py     # 问题生成Prompt
│   ├── emotion_prompts.py      # 情绪识别Prompt
│   └── summary_prompts.py      # 内容归纳Prompt
├── config/
│   ├── __init__.py
│   └── llm_config.py           # LLM配置
└── ...
```

### 3.2 LLMService 设计

```python
# src/services/llm_service.py
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
from langchain_anthropic import ChatAnthropic

from config.llm_config import LLMConfig
from prompts.base import PromptTemplate

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
        
        if model_config.provider == "openai":
            self._model = ChatOpenAI(
                model=model_config.model_name,
                temperature=model_config.temperature,
                max_tokens=model_config.max_tokens,
                api_key=model_config.api_key,
                base_url=model_config.base_url,
            )
        elif model_config.provider == "anthropic":
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
        """加载所有Prompt模板"""
        from prompts import question_prompts, emotion_prompts, summary_prompts
        
        self._prompt_templates.update(question_prompts.TEMPLATES)
        self._prompt_templates.update(emotion_prompts.TEMPLATES)
        self._prompt_templates.update(summary_prompts.TEMPLATES)
        
        logger.info(f"Loaded {len(self._prompt_templates)} prompt templates")
    
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
        prompt = template.render(**variables)
        
        # 构建结构化输出的Prompt
        structured_prompt = f"""{prompt}

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
        
        for attempt in range(max_retries):
            try:
                response = await self.model.ainvoke(messages, **kwargs)
                return response
            except Exception as e:
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
        from config.llm_config import get_default_config
        _llm_service_instance = LLMService(get_default_config())
    return _llm_service_instance


def init_llm_service(config: LLMConfig) -> LLMService:
    """初始化全局LLMService实例"""
    global _llm_service_instance
    _llm_service_instance = LLMService(config)
    return _llm_service_instance
```

### 3.3 LLMConfig 配置对象

```python
# src/config/llm_config.py
from pydantic import BaseModel, Field
from typing import Optional
import os


class LLMConfig(BaseModel):
    """
    LLM配置
    
    支持的环境变量：
    - LLM_PROVIDER: 模型提供商 (openai/anthropic)
    - LLM_MODEL_NAME: 模型名称
    - LLM_API_KEY: API密钥
    - LLM_BASE_URL: API基础URL（可选）
    - LLM_TEMPERATURE: 温度参数
    - LLM_MAX_TOKENS: 最大Token数
    """
    
    provider: str = Field(default="openai", description="模型提供商")
    model_name: str = Field(default="gpt-4o", description="模型名称")
    api_key: str = Field(..., description="API密钥")
    base_url: Optional[str] = Field(default=None, description="API基础URL")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    max_tokens: int = Field(default=4096, ge=1, description="最大Token数")
    
    # 重试配置
    max_retries: int = Field(default=3, description="最大重试次数")
    retry_delay: float = Field(default=1.0, description="重试延迟（秒）")
    
    # 超时配置
    timeout: float = Field(default=60.0, description="请求超时（秒）")
    
    @classmethod
    def from_env(cls) -> "LLMConfig":
        """从环境变量加载配置"""
        return cls(
            provider=os.getenv("LLM_PROVIDER", "openai"),
            model_name=os.getenv("LLM_MODEL_NAME", "gpt-4o"),
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
        )


def get_default_config() -> LLMConfig:
    """获取默认配置"""
    return LLMConfig.from_env()
```

### 3.4 Prompt模板基类

```python
# src/prompts/base.py
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from string import Template


class PromptTemplate(BaseModel):
    """
    Prompt模板
    
    属性：
    - name: 模板名称
    - description: 模板描述
    - system_prompt: 系统提示
    - user_template: 用户提示模板
    - variables: 模板变量说明
    """
    
    name: str = Field(..., description="模板名称")
    description: str = Field(default="", description="模板描述")
    system_prompt: Optional[str] = Field(default=None, description="系统提示")
    user_template: str = Field(..., description="用户提示模板")
    variables: Dict[str, str] = Field(default_factory=dict, description="变量说明")
    
    def render(self, **kwargs) -> str:
        """渲染模板"""
        template = Template(self.user_template)
        return template.safe_substitute(**kwargs)
    
    def validate_variables(self, **kwargs) -> bool:
        """验证变量是否完整"""
        required = set(self.variables.keys())
        provided = set(kwargs.keys())
        return required.issubset(provided)
```

### 3.5 各场景Prompt模板

```python
# src/prompts/question_prompts.py
from .base import PromptTemplate

TEMPLATES = {
    "question_generation": PromptTemplate(
        name="question_generation",
        description="生成下一个对话问题",
        system_prompt="""你是一位专业的采访记者，正在采访一位老人撰写自传。
你的任务是：
1. 基于老人之前的回答，生成下一个合适的采访问题
2. 问题要具体、开放，引导老人回忆细节
3. 注意照顾老人的情绪，措辞要温和
4. 一次只问一个问题

采访策略：
- 闪光点优先：从印象最深的事开始，向前后延伸
- 时间线经典：童年→少年→青年→中年→老年顺序推进
- 主题式发散：围绕特定主题深入挖掘

人生阶段：
- childhood: 童年 (0-12岁)
- youth: 少年 (13-18岁)
- young_adult: 青年 (19-35岁)
- middle_age: 中年 (36-60岁)
- elderly: 老年 (60岁+)
""",
        user_template="""## 当前状态
- 采访策略：$strategy
- 当前阶段：$current_phase
- 对话轮数：$turn_count
- 各阶段覆盖率：$coverage

## 用户回答
$user_input

## 相关记忆
$related_memory

## 待追问问题
$pending_questions

## 情绪状态
- 情绪类型：$emotion_type
- 情绪强度：$emotion_intensity

请基于以上信息，生成下一个采访问题。只输出问题本身，不要其他内容。
""",
        variables={
            "strategy": "当前采访策略",
            "current_phase": "当前人生阶段",
            "turn_count": "对话轮数",
            "coverage": "各阶段覆盖率",
            "user_input": "用户的最新回答",
            "related_memory": "相关记忆内容",
            "pending_questions": "待追问问题列表",
            "emotion_type": "情绪类型",
            "emotion_intensity": "情绪强度",
        }
    ),
    
    "emotion_response": PromptTemplate(
        name="emotion_response",
        description="生成情绪响应话术",
        system_prompt="""你是一位有同理心的采访者。
当老人情绪波动时，你需要：
1. 表达理解和关心
2. 给予情感支持
3. 适时建议休息或换话题
4. 保持温和的语气

不要说教或评判，只表达关心。
""",
        user_template="""老人刚才说：
"$user_input"

情绪分析：
- 情绪类型：$emotion_type
- 情绪强度：$emotion_intensity
- 建议动作：$suggested_action

请生成一个合适的情感响应。如果是高强度负面情绪，建议老人休息一下。
只输出响应内容，不要其他说明。
""",
        variables={
            "user_input": "用户的输入",
            "emotion_type": "情绪类型",
            "emotion_intensity": "情绪强度",
            "suggested_action": "建议动作",
        }
    ),
}


# src/prompts/emotion_prompts.py
from .base import PromptTemplate

TEMPLATES = {
    "emotion_detection": PromptTemplate(
        name="emotion_detection",
        description="识别用户情绪状态",
        system_prompt="""你是一位情绪分析专家。
你需要分析老人在采访过程中的情绪状态。

情绪类型：
正向：joy(喜悦), pride(自豪), nostalgia(怀念), gratitude(感恩), hope(希望)
中性：neutral(平静), curious(好奇), contemplative(沉思)
负向：sadness(悲伤), regret(后悔), anger(愤怒), fear(恐惧), guilt(愧疚)
特殊：confusion(困惑), fatigue(疲劳), reluctance(抗拒)

情绪强度：low(低), medium(中), high(高)
情绪极性：positive(正向), neutral(中性), negative(负向)

建议动作：
- continue: 继续正常对话
- pause: 建议暂停
- comfort: 需要安慰
- redirect: 需要换话题
""",
        user_template="""请分析以下对话内容的情绪状态：

用户输入：
"$user_input"

最近的对话历史：
$conversation_history

请输出JSON格式的情绪分析结果。
""",
        variables={
            "user_input": "用户的输入",
            "conversation_history": "最近的对话历史",
        }
    ),
}


# src/prompts/summary_prompts.py
from .base import PromptTemplate

TEMPLATES = {
    "content_extraction": PromptTemplate(
        name="content_extraction",
        description="从对话中提取结构化信息",
        system_prompt="""你是一位信息提取专家。
你需要从老人的对话中提取结构化信息，用于撰写自传。

需要提取的信息类型：
1. 事件（EventInfo）：
   - 事件标题、时间、地点、类型
   - 事件描述、关键细节
   - 参与人物、情感标签
   - 事件意义

2. 人物（PersonInfo）：
   - 姓名、角色/关系
   - 人物描述
   - 对主人公的影响

3. 时间标记（TimeMarker）：
   - 时间点
   - 相关事件ID
   - 人生阶段

4. 主题（ThemeInfo）：
   - 主题名称
   - 相关事件
   - 描述

注意事项：
- 只提取明确提到的信息，不要编造
- 时间信息可能模糊，标注精度（年/月/日）
- 人物关系要准确
""",
        user_template="""请从以下对话内容中提取结构化信息：

用户输入：
"$user_input"

对话轮次：$turn_id

请输出JSON格式的提取结果。
""",
        variables={
            "user_input": "用户的输入",
            "turn_id": "对话轮次ID",
        }
    ),
}
```

---

## 四、开发要求

### 4.1 代码规范

```python
# 1. 所有方法必须是async
async def invoke(self, prompt: str) -> LLMCallResult:
    pass

# 2. 使用Pydantic进行数据验证
class LLMConfig(BaseModel):
    pass

# 3. 错误处理必须返回LLMCallResult，不抛出异常
result = LLMCallResult(success=False, error=str(e))

# 4. 所有Prompt模板必须集中管理
TEMPLATES = {
    "template_name": PromptTemplate(...),
}

# 5. 日志记录关键操作
logger.info(f"LLM call: {template_name}")
logger.error(f"LLM call failed: {e}")
```

### 4.2 单元测试要求

```python
# tests/test_llm_service.py
import pytest
from unittest.mock import AsyncMock, patch
from services.llm_service import LLMService, LLMCallResult
from config.llm_config import LLMConfig
from models import EmotionResult

class TestLLMService:
    @pytest.fixture
    def llm_service(self):
        config = LLMConfig(
            provider="openai",
            model_name="gpt-4o",
            api_key="test-key",
        )
        return LLMService(config)
    
    @pytest.mark.asyncio
    async def test_invoke_success(self, llm_service):
        """测试成功调用"""
        with patch.object(llm_service._model, 'ainvoke', new_callable=AsyncMock) as mock:
            mock.return_value.content = "测试响应"
            
            result = await llm_service.invoke("你好")
            
            assert result.success
            assert result.content == "测试响应"
    
    @pytest.mark.asyncio
    async def test_invoke_with_retry(self, llm_service):
        """测试重试机制"""
        with patch.object(llm_service._model, 'ainvoke', new_callable=AsyncMock) as mock:
            # 前两次失败，第三次成功
            mock.side_effect = [
                Exception("Error 1"),
                Exception("Error 2"),
                type('obj', (object,), {'content': '成功'})()
            ]
            
            result = await llm_service.invoke("测试重试")
            
            assert result.success
            assert mock.call_count == 3
    
    @pytest.mark.asyncio
    async def test_invoke_structured(self, llm_service):
        """测试结构化输出"""
        with patch.object(llm_service, 'invoke', new_callable=AsyncMock) as mock:
            mock.return_value = LLMCallResult(
                success=True,
                content='{"emotion_type": "neutral", "intensity": "low"}',
            )
            
            result, raw = await llm_service.invoke_structured(
                template_name="emotion_detection",
                variables={"user_input": "测试", "conversation_history": ""},
                output_model=EmotionResult,
            )
            
            assert result is not None
            assert result.emotion_type == "neutral"
    
    def test_get_stats(self, llm_service):
        """测试统计信息"""
        llm_service._call_history = [
            LLMCallResult(success=True, latency_ms=100),
            LLMCallResult(success=True, latency_ms=200),
            LLMCallResult(success=False, latency_ms=50),
        ]
        
        stats = llm_service.get_stats()
        
        assert stats["total_calls"] == 3
        assert stats["success_rate"] == pytest.approx(2/3)
```

### 4.3 验收标准

- [ ] LLMService实现完成
- [ ] LLMConfig实现完成
- [ ] PromptTemplate基类实现完成
- [ ] 所有Prompt模板定义完成（question/emotion/summary）
- [ ] 支持OpenAI和Anthropic两种Provider
- [ ] 重试机制工作正常
- [ ] 结构化输出功能正常
- [ ] 单元测试覆盖率 > 80%
- [ ] 所有测试通过
- [ ] 日志记录完整

---

## 五、使用示例

### 5.1 在QuestionGenerator中使用

```python
# src/services/question_generator.py
from services.llm_service import LLMService, get_llm_service

class QuestionGenerator:
    def __init__(self, llm_service: LLMService = None):
        self.llm_service = llm_service or get_llm_service()
    
    async def generate(self, user_input, emotion, memory, state) -> str:
        # 构建模板变量
        variables = {
            "strategy": state.strategy,
            "current_phase": state.current_phase,
            "turn_count": state.turn_count,
            "coverage": str(state.coverage),
            "user_input": user_input,
            "related_memory": self._format_memory(memory),
            "pending_questions": str(state.pending_questions),
            "emotion_type": emotion.emotion_type,
            "emotion_intensity": emotion.intensity,
        }
        
        # 调用LLMService
        result = await self.llm_service.invoke_with_template(
            template_name="question_generation",
            variables=variables,
        )
        
        if not result.success:
            # 降级：返回默认问题
            return self._get_default_question(state.current_phase)
        
        return result.content
```

### 5.2 在EmotionDetector中使用

```python
# src/services/emotion_detector.py
from services.llm_service import LLMService, get_llm_service
from models import EmotionResult

class EmotionDetector:
    def __init__(self, llm_service: LLMService = None):
        self.llm_service = llm_service or get_llm_service()
    
    async def detect(self, user_input, conversation_history) -> EmotionResult:
        variables = {
            "user_input": user_input,
            "conversation_history": self._format_history(conversation_history),
        }
        
        result, raw = await self.llm_service.invoke_structured(
            template_name="emotion_detection",
            variables=variables,
            output_model=EmotionResult,
        )
        
        if result is None:
            # 降级：返回默认中性情绪
            return EmotionResult.default_neutral()
        
        return result
```

---

## 六、参考资源

### 6.1 相关文档

- [问答引导层Agent-系统架构设计.md](../问答引导层Agent-系统架构设计.md)
- [LangChain文档](https://python.langchain.com/)
- [Pydantic文档](https://docs.pydantic.dev/)

### 6.2 设计原则

1. **单一职责**：LLMService只负责模型调用，不处理业务逻辑
2. **依赖注入**：通过构造函数注入，便于测试
3. **错误隔离**：调用失败返回错误结果，不抛出异常
4. **可观测性**：完整的日志和统计

---

## 七、注意事项

1. **API密钥安全**：不要在代码中硬编码API密钥，使用环境变量
2. **Token限制**：注意模型的Token限制，合理设置max_tokens
3. **成本控制**：在生产环境添加调用限制和告警
4. **超时处理**：设置合理的超时时间，避免长时间等待
5. **降级策略**：模型调用失败时要有降级方案
