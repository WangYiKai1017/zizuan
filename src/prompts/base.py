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
        template = Template(self.system_prompt)
        return template.safe_substitute(**kwargs)
    
    def validate_variables(self, **kwargs) -> bool:
        """验证变量是否完整"""
        required = set(self.variables.keys())
        provided = set(kwargs.keys())
        return required.issubset(provided)