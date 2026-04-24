from pydantic import BaseModel, Field
from typing import List


class PersonInfo(BaseModel):
    """
    人物信息
    
    职责：
    - 结构化记录人物画像
    - 支持写入记忆库
    
    使用场景：
    - ContentSummarizer 的提取结果
    - MarkdownFileManager 写入文件
    - HandoffPackage 的组成部分
    """
    
    person_id: str = Field(..., description="人物ID")
    name: str = Field(..., description="姓名")
    role: str = Field(..., description="角色/关系")
    # immediate_family/extended_family/spouse/friend/colleague/mentor/classmate/neighbor
    
    description: str = Field(default="", description="人物描述")
    relation_to_protagonist: str = Field(default="", description="与主人公的关系")
    source_events: List[str] = Field(default_factory=list, description="相关事件ID")
    
    # 可选扩展字段
    birth_year: str = Field(default="", description="出生年份")
    characteristics: List[str] = Field(default_factory=list, description="性格特征")
    influence: str = Field(default="", description="对主人公的影响")
    quotes: List[str] = Field(default_factory=list, description="重要语录")
    
    def to_markdown(self) -> str:
        """转换为Markdown格式"""
        related_events = "\n".join([f"- [[../events/{e}.md|{e}]]" for e in self.source_events])
        quotes_section = "\n".join([f"> {q}" for q in self.quotes]) if self.quotes else "暂无"
        
        return f"""# {self.name}

## 基本信息
- **关系**：{self.role}
- **姓名**：{self.name}
- **描述**：{self.description}

## 与主人公的关系
{self.relation_to_protagonist if self.relation_to_protagonist else "待补充"}

## 对主人公的影响
{self.influence if self.influence else "待补充"}

## 相关事件
{related_events if self.source_events else "暂无"}

## 重要语录
{quotes_section}

## 来源记录
- 来源事件：{', '.join(self.source_events) if self.source_events else '无'}
- 确认状态：待确认 [ ]
"""