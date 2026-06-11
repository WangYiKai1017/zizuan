from pydantic import BaseModel, Field
from typing import Optional
import os
from dotenv import load_dotenv

# 加载.env文件
load_dotenv()


class LLMConfig(BaseModel):
    """
    LLM配置
    
    支持的环境变量：
    - 通用配置:
      - LLM_PROVIDER: 模型提供商 (openai/anthropic/deepseek)
      - LLM_MODEL_NAME: 模型名称
      - LLM_API_KEY: API密钥
      - LLM_BASE_URL: API基础URL（可选）
      - LLM_TEMPERATURE: 温度参数
      - LLM_MAX_TOKENS: 最大Token数
    
    - DeepSeek专属配置:
      - DEEPSEEK_URL: DeepSeek API URL
      - DEEPSEEK_APIKEY: DeepSeek API密钥
      - DEEPSEEK_MODEL_NAME: DeepSeek模型名称（可选）
    """
    
    provider: str = Field(default="deepseek", description="模型提供商")
    model_name: str = Field(default="deepseek-v4-flash", description="模型名称")
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
        """从环境变量加载配置，使用DeepSeek专属配置。"""
        return cls.from_env_deepseek()
        
    @classmethod
    def from_env_deepseek(cls) -> "LLMConfig":
        """从环境变量加载配置，使用Deepseek专属配置"""
        # 优先检查Deepseek专属配置
        deepseek_url = os.getenv("DEEPSEEK_URL")
        deepseek_apikey = os.getenv("DEEPSEEK_APIKEY")
        
        if deepseek_url and deepseek_apikey:
            return cls(
                provider="deepseek",
                model_name=os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-v4-flash"),
                api_key=deepseek_apikey,
                base_url=deepseek_url,
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            )
        
        raise ValueError("未配置Deepseek专属API密钥或URL")


def get_default_config() -> LLMConfig:
    """获取默认配置，使用DeepSeek模型。"""
    return LLMConfig.from_env_deepseek()
