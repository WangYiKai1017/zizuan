# LangGraph Agent 模式详解

## 模式选择指南

| 场景 | 推荐模式 | 理由 |
|------|----------|------|
| 分析文档/数据并产生摘要 | Analyzer | 专注推理，无输出格式负担 |
| 根据条件分支工作流 | Router | LLM 理解语义，非硬编码规则 |
| 生成 API 响应/数据库记录 | Compiler | 强制类型验证，减少幻觉 |
| 复杂多步骤任务 | Analyzer → Router → Compiler | 分离关注点，每层专注单一职责 |

---

## Pattern 1: Analyzer Agent

### 完整实现

```python
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from typing import List, Optional
import asyncio

class AnalyzerAgent:
    """
    通用分析器 Agent
    
    领域知识完全由 prompt 和工具注入，同一类可复用至：
    - 财务分析
    - 法律文档审查
    - 客户支持工单分类
    - 数据质量评估
    """
    
    def __init__(
        self,
        llm: BaseChatModel,
        tools: List[BaseTool],
        prompt: str,
        max_iterations: int = 10,
    ):
        self._llm = llm
        self._tools = tools
        self._prompt = prompt
        self._max_iterations = max_iterations
    
    async def analyze(self, context: str, conversation_history: Optional[List[dict]] = None) -> str:
        """
        执行分析循环
        
        Args:
            context: 用户问题或任务描述
            conversation_history: 可选的对话历史
        
        Returns:
            分析结果摘要
        """
        llm_with_tools = self._llm.bind_tools(self._tools)
        
        messages = [
            {"role": "system", "content": self._prompt},
            {"role": "user", "content": context},
        ]
        
        if conversation_history:
            messages = messages[:1] + conversation_history + messages[1:]
        
        iteration = 0
        while iteration < self._max_iterations:
            iteration += 1
            
            # 调用 LLM
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)
            
            # 检查是否完成
            if not response.tool_calls:
                return response.content
            
            # 执行工具调用
            for tool_call in response.tool_calls:
                tool = self._find_tool(tool_call["name"])
                if tool is None:
                    messages.append({
                        "role": "tool",
                        "content": f"Error: Tool '{tool_call['name']}' not found",
                        "tool_call_id": tool_call["id"],
                    })
                    continue
                
                try:
                    result = await tool.ainvoke(tool_call["args"])
                    messages.append({
                        "role": "tool",
                        "content": str(result),
                        "tool_call_id": tool_call["id"],
                    })
                except Exception as e:
                    messages.append({
                        "role": "tool",
                        "content": f"Error executing {tool_call['name']}: {str(e)}",
                        "tool_call_id": tool_call["id"],
                    })
        
        return "Analysis incomplete: reached maximum iterations"
    
    def _find_tool(self, name: str) -> Optional[BaseTool]:
        for tool in self._tools:
            if tool.name == name:
                return tool
        return None
```

### 使用示例

```python
# 财务分析场景
FINANCIAL_ANALYZER_PROMPT = """你是资深金融分析师。分析提供的财务数据并总结：

## 分析维度
1. 营收表现：同比/环比增长，vs 市场共识
2. 利润率：毛利率、净利率变化趋势
3. 现金流：经营性现金流是否健康
4. 风险因素：重大诉讼、监管问题、客户集中度

## 输出要求
- 使用具体数字支持结论
- 标注异常变化（>20% 波动）
- 用简洁的商业语言，避免 jargon
"""

analyzer = AnalyzerAgent(
    llm=ChatOpenAI(model="gpt-4-turbo-preview"),
    tools=[fetch_10q_tool, fetch_transcript_tool, get_consensus_tool],
    prompt=FINANCIAL_ANALYZER_PROMPT,
)

result = await analyzer.analyze("分析 AAPL 2024 Q4 财报")
```

---

## Pattern 2: Router Agent

### 完整实现

```python
from typing import Optional, List, Literal
from pydantic import BaseModel

class RoutingTool:
    """
    路由决策工具
    
    关键设计：
    - 路由选择存储为状态，供 LangGraph 条件边读取
    - 支持 error_details 用于调试
    """
    
    def __init__(self):
        self._route: Optional[str] = None
        self._error_details: Optional[str] = None
    
    @property
    def route(self) -> Optional[str]:
        return self._route
    
    @property
    def error_details(self) -> Optional[str]:
        return self._error_details
    
    def reset(self):
        self._route = None
        self._error_details = None
    
    async def select_route(
        self,
        route: Optional[str] = None,
        error_details: Optional[str] = None,
    ) -> str:
        """
        LLM 调用此工具来选择路由
        
        Args:
            route: 选择的路由名称（必须匹配预定义选项）
            error_details: 如果无法决定，说明原因
        """
        if error_details:
            self._route = None
            self._error_details = error_details
            return f"Routing failed: {error_details}"
        
        self._route = route
        self._error_details = None
        return f"Route selected: {route}"


class RouterAgent:
    """
    路由决策 Agent
    
    适用于需要理解非结构化文本后做分支决策的场景
    """
    
    def __init__(
        self,
        llm: BaseChatModel,
        routing_tool: RoutingTool,
        prompt: str,
        available_routes: List[str],
    ):
        self._llm = llm
        self._routing_tool = routing_tool
        self._prompt = prompt
        self._available_routes = available_routes
    
    @property
    def route(self) -> Optional[str]:
        return self._routing_tool.route
    
    async def decide(self, context: str) -> Optional[str]:
        """
        执行路由决策
        
        Args:
            context: 上游分析结果或输入内容
        
        Returns:
            选择的路由名称，或 None（如果决策失败）
        """
        self._routing_tool.reset()
        
        # 增强 prompt，明确可用路由
        enhanced_prompt = f"""{self._prompt}

可用路由选项（必须选择其一）:
{chr(10).join(f'- {route}' for route in self._available_routes)}

重要：调用 select_route 时，route 参数必须是上述选项之一。"""
        
        llm_with_tools = self._llm.bind_tools([self._routing_tool.select_route])
        
        messages = [
            {"role": "system", "content": enhanced_prompt},
            {"role": "user", "content": context},
        ]
        
        response = await llm_with_tools.ainvoke(messages)
        
        # 执行工具调用以存储路由
        if response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call["name"] == "select_route":
                    await self._routing_tool.select_route(**tool_call["args"])
                    break
        
        return self._routing_tool.route
```

### LangGraph 集成示例

```python
from langgraph.graph import StateGraph, END

class WorkflowState(TypedDict):
    messages: Sequence[BaseMessage]
    selected_route: Optional[str]
    analysis_result: str

def create_routed_workflow():
    # 创建路由工具和分析器
    routing_tool = RoutingTool()
    router = RouterAgent(
        llm=ChatOpenAI(model="gpt-4-turbo-preview"),
        routing_tool=routing_tool,
        prompt=DOCUMENT_ROUTER_PROMPT,
        available_routes=["earnings_deep_dive", "standard_summary", "risk_alert"],
    )
    
    # 定义节点
    async def router_node(state: WorkflowState):
        route = await router.decide(state["analysis_result"])
        return {"selected_route": route}
    
    async def deep_analysis_node(state: WorkflowState):
        # 深度分析逻辑
        ...
    
    async def standard_summary_node(state: WorkflowState):
        # 标准摘要逻辑
        ...
    
    async def risk_alert_node(state: WorkflowState):
        # 风险告警逻辑
        ...
    
    # 条件边函数
    def route_decision(state: WorkflowState):
        route = state["selected_route"]
        mapping = {
            "earnings_deep_dive": "deep_analysis",
            "standard_summary": "standard_summary",
            "risk_alert": "risk_alert",
        }
        return mapping.get(route, "error_handler")
    
    # 构建图
    workflow = StateGraph(WorkflowState)
    workflow.add_node("router", router_node)
    workflow.add_node("deep_analysis", deep_analysis_node)
    workflow.add_node("standard_summary", standard_summary_node)
    workflow.add_node("risk_alert", risk_alert_node)
    workflow.add_node("error_handler", lambda s: {"error": "Unknown route"})
    
    workflow.set_entry_point("router")
    workflow.add_conditional_edges("router", route_decision)
    
    return workflow.compile()
```

---

## Pattern 3: Report Compiler

### 完整实现

```python
from pydantic import BaseModel, Field
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from typing import List, Type, get_origin, get_args, Literal
import json


def build_extraction_prompt(schema: Type[BaseModel]) -> str:
    """
    从 Pydantic 模型动态生成提取 Prompt
    
    优势：
    - 避免手动维护 schema 和 prompt 的同步
    - 减少字段遗漏或类型错误
    """
    schema_json = schema.model_json_schema()
    
    # 生成字段描述
    field_descriptions = []
    for field_name, field_info in schema.model_fields.items():
        field_type = field_info.annotation
        description = field_info.description or ""
        field_descriptions.append(f"- {field_name} ({field_type.__name__}): {description}")
    
    return f"""你是专业的数据提取助手。从对话历史中提取信息，填充以下数据结构：

## 目标 Schema
{json.dumps(schema_json, indent=2, ensure_ascii=False)}

## 字段说明
{chr(10).join(field_descriptions)}

## 提取规则
1. **只基于事实**：所有字段值必须能从对话中找到依据，禁止编造
2. **缺失处理**：无法确定的字段设为 null，不要猜测
3. **类型严格**：数字、日期、枚举值必须符合 schema 定义
4. **保持原文**：引用数据时保留原始格式（如货币符号、单位）

## 输出
直接返回符合 schema 的 JSON 对象，不要额外解释。"""


class ReportCompiler:
    """
    结构化报告编译器
    
    用于多 Agent 工作流的最后一步，将分析结果转换为：
    - API 响应
    - 数据库记录
    - 报告文档
    """
    
    def __init__(
        self,
        llm: BaseChatModel,
        schema: Type[BaseModel],
        custom_prompt: Optional[str] = None,
    ):
        self._llm = llm
        self._schema = schema
        self._prompt = custom_prompt or build_extraction_prompt(schema)
    
    async def compile(self, messages: List[BaseMessage]) -> BaseModel:
        """
        从对话历史编译结构化报告
        
        Args:
            messages: 对话历史（包含所有分析结果）
        
        Returns:
            填充好的 Pydantic 模型实例
        """
        structured_llm = self._llm.with_structured_output(self._schema)
        
        all_messages = [
            {"role": "system", "content": self._prompt},
        ] + messages
        
        result = await structured_llm.ainvoke(all_messages)
        return result
```

### 使用示例

```python
# 定义输出 Schema
class FinancialReport(BaseModel):
    company_name: str = Field(description="公司名称")
    report_period: str = Field(description="报告期间，如 '2024 Q4'")
    revenue: Optional[float] = Field(description="营收（美元）")
    revenue_growth_yoy: Optional[float] = Field(description="营收同比增长率 (%)")
    eps: Optional[float] = Field(description="每股收益")
    eps_vs_consensus: str = Field(description="EPS vs 共识：'beat', 'miss', 'inline'")
    guidance_change: Literal["raised", "maintained", "lowered", "unknown"] = Field(
        description="管理层指引变化"
    )
    key_risks: List[str] = Field(description="关键风险因素列表")
    analyst_summary: str = Field(description="分析师总结，2-3 句话")

# 创建编译器
compiler = ReportCompiler(
    llm=ChatOpenAI(model="gpt-4-turbo-preview"),
    schema=FinancialReport,
)

# 编译报告
report = await compiler.compile(conversation_messages)

# 访问结构化数据
print(f"{report.company_name} 营收增长：{report.revenue_growth_yoy}%")
print(f"关键风险：{', '.join(report.key_risks)}")
```

---

## 组合使用：完整工作流

```python
async def run_financial_analysis_pipeline(company: str, period: str):
    """
    完整的财务分析工作流：
    Analyzer → Router → Compiler
    """
    # 1. 分析阶段
    analyzer = AnalyzerAgent(
        llm=ChatOpenAI(model="gpt-4-turbo-preview"),
        tools=[fetch_filings_tool, get_market_data_tool],
        prompt=FINANCIAL_ANALYZER_PROMPT,
    )
    analysis = await analyzer.analyze(f"分析 {company} {period} 财报")
    
    # 2. 路由阶段
    routing_tool = RoutingTool()
    router = RouterAgent(
        llm=ChatOpenAI(model="gpt-4-turbo-preview"),
        routing_tool=routing_tool,
        prompt=DOCUMENT_ROUTER_PROMPT,
        available_routes=["earnings_deep_dive", "standard_summary", "risk_alert"],
    )
    route = await router.decide(analysis)
    
    # 3. 根据路由选择后续处理
    if route == "earnings_deep_dive":
        # 深度分析...
        pass
    elif route == "risk_alert":
        # 风险告警流程...
        pass
    
    # 4. 编译最终报告
    compiler = ReportCompiler(
        llm=ChatOpenAI(model="gpt-4-turbo-preview"),
        schema=FinancialReport,
    )
    
    # 收集所有消息
    all_messages = [
        HumanMessage(content=f"分析 {company} {period} 财报"),
        AIMessage(content=analysis),
    ]
    
    report = await compiler.compile(all_messages)
    return report
```
