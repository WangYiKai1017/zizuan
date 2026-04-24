from pydantic import BaseModel, Field
from typing import List, Optional


class EventInfo(BaseModel):
    """
    事件信息
    
    职责：
    - 结构化记录单个事件
    - 支持写入记忆库
    
    使用场景：
    - ContentSummarizer 的提取结果
    - MarkdownFileManager 写入文件
    - HandoffPackage 的组成部分
    """
    
    event_id: str = Field(..., description="事件ID")
    title: str = Field(..., description="事件标题")
    time: str = Field(..., description="时间描述")
    time_precision: str = Field(default="year", description="时间精度: year/month/day")
    location: str = Field(default="", description="地点")
    type: str = Field(default="other", description="事件类型")
    # birth/education/career/marriage/relocation/achievement/challenge/travel/historical/other
    
    description: str = Field(..., description="事件描述")
    details: List[str] = Field(default_factory=list, description="关键细节")
    participants: List[str] = Field(default_factory=list, description="参与人物")
    emotions: List[str] = Field(default_factory=list, description="情感标签")
    significance: str = Field(default="", description="事件意义")
    source_turns: List[int] = Field(default_factory=list, description="来源对话轮次")
    
    def to_markdown(self) -> str:
        """转换为Markdown格式"""
        details_section = "\n".join([f"- {d}" for d in self.details]) if self.details else "暂无"
        emotion_tags = " ".join([f"#{e}" for e in self.emotions]) if self.emotions else "#待补充"
        participants_section = "\n".join([f"- [[../people/{p}.md|{p}]]" for p in self.participants])
        source_turns_str = ", ".join([f"session_001, turn_{t}" for t in self.source_turns])
        
        return f"""# {self.title}

## 基本信息
- **时间**：{self.time}
- **地点**：{self.location}
- **事件类型**：{self.type}

## 事件描述
{self.description}

## 相关人物
{participants_section if self.participants else "暂无"}

## 时间线关联
- [[../timeline/life-events.md#{self.time}|人生大事年表]]

## 关键细节
{details_section}

## 情感标签
{emotion_tags}

## 来源
- 对话记录：{source_turns_str}
- 确认状态：待确认 [ ]

## 待补充
- [ ] 待补充详细信息
"""