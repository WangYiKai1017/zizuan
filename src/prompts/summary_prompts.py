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
- 人物关系要准确""",
        user_template="""请从以下对话内容中提取结构化信息：

用户输入：
"$user_input"

对话轮次：$turn_id

请输出JSON格式的提取结果。""",
        variables={
            "user_input": "用户的输入",
            "turn_id": "对话轮次ID",
        }
    ),
}