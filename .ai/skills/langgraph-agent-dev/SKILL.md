---
name: langgraph-agent-dev
description: LangChain/LangGraph 智能体开发规范与最佳实践。当需要基于 LangChain 或 LangGraph 框架构建 AI Agent、设计工具 (Tools)、定义状态图 (StateGraph)、实现 ReAct 模式、配置记忆与持久化、或开发多 Agent 协作系统时使用此技能。涵盖生产级 Agent 的完整开发流程：工具设计、状态管理、图编排、错误处理、可观测性配置。
---

# LangChain/LangGraph Agent 开发指南

## 核心原则

### 1. 分离关注点 (Separation of Concerns)

**不要**让单个 Agent 承担所有职责。将以下认知任务分离：

| 任务类型 | 职责 | 输出 |
|----------|------|------|
| **Analyzer** | 分析数据、调用工具推理 | 自由文本摘要 |
| **Router** | 根据分析结果决定工作流分支 | 路由选择 |
| **Compiler** | 提取结构化数据 | 验证的 Pydantic 模型 |

### 2. 工具设计原则

**优秀的 Tool 设计要点：**

- **Docstring 详尽**：包含使用场景示例，LLM 依靠 docstring 判断何时调用工具
- **签名简洁**：只暴露 LLM 能提供的参数，依赖注入使用工厂函数闭包
- **返回结构化数据 + 摘要**：同时返回原始数据和预计算的摘要字段
- **限制结果数量**：返回 20-50 条结果避免上下文溢出

```python
from langchain_core.tools import tool

@tool
def search_transactions(
    keywords: str | None = None,
    category: str | None = None
) -> dict:
    """搜索金融交易记录。
    
    使用场景：
    - 查询特定商户消费（"我在星巴克花了多少钱？"）
    - 查询分类消费（"这个月 groceries 花了多少？"）
    - 组合查询（"麦当劳的餐饮消费"）
    
    参数：
        keywords: 商户名称关键词
        category: 消费分类（如 "Groceries", "Gas"）
    
    返回：
        包含 transactions 列表、total_amount、count、summary 的字典
    """
    # 实现...
    return {
        "transactions": [...],      # 详细数据（限制 20 条）
        "total_amount": 1245.67,    # 预计算总额
        "count": 23,                # 总数量
        "summary": "Found 23 transactions totaling $1,245.67"  # 自然语言摘要
    }
```

### 3. 状态管理 (Agent State)

**状态是 Agent 的单一事实来源**。使用 TypedDict 定义：

```python
from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    """Agent 执行过程中传递的状态"""
    messages: Annotated[Sequence[BaseMessage], "对话历史"]
    user_id: str                    # 用户标识（避免每层传递）
    retry_count: int                # 检测循环，优雅退出
    last_tool_used: str | None      # 避免重复调用
```

**状态随执行增长**：
```
初始：{"messages": []}
用户提问：{"messages": [HumanMessage("...")]}
调用工具：{"messages": [HumanMessage(...), AIMessage(tool_calls=[...]), ToolMessage({...})]}
回复：{"messages": [..., AIMessage("答案")]}
```

## 核心模式

### 模式 1: Analyzer Agent（分析器）

**用途**：调查数据、产生人类可读的分析摘要

```python
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from typing import List

class AnalyzerAgent:
    """通用分析器 - 领域知识在 prompt 和工具中"""
    
    def __init__(self, llm: BaseChatModel, tools: List[BaseTool], prompt: str):
        self._llm = llm
        self._tools = tools
        self._prompt = prompt
    
    async def analyze(self, context: str) -> str:
        llm_with_tools = self._llm.bind_tools(self._tools)
        messages = [
            {"role": "system", "content": self._prompt},
            {"role": "user", "content": context},
        ]
        
        while True:
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)
            
            if not response.tool_calls:
                return response.content  # 完成推理
            
            # 执行工具调用
            for tool_call in response.tool_calls:
                tool = next(t for t in self._tools if t.name == tool_call["name"])
                result = await tool.ainvoke(tool_call["args"])
                messages.append({
                    "role": "tool",
                    "content": str(result),
                    "tool_call_id": tool_call["id"],
                })
```

**Prompt 示例**：
```python
FINANCIAL_ANALYSIS_PROMPT = """你是金融分析专家。分析公司财报并总结：
- 营收和 EPS vs 市场共识
- 管理层指引变化（上调/维持/下调）
- 关键风险因素
- 业务板块表现变化

使用提供的工具获取数据，然后给出清晰摘要。"""
```

### 模式 2: Router Agent（路由器）

**用途**：根据分析结果决定工作流分支

```python
from typing import Optional

class RoutingTool:
    """存储 LLM 的路由决策"""
    
    def __init__(self):
        self._route: Optional[str] = None
    
    @property
    def route(self) -> Optional[str]:
        return self._route
    
    async def select_route(
        self,
        route: Optional[str] = None,
        error_details: Optional[str] = None,
    ) -> str:
        if error_details:
            self._route = None
            return f"Routing failed: {error_details}"
        self._route = route
        return f"Route selected: {route}"

class RouterAgent:
    def __init__(self, llm: BaseChatModel, routing_tool: RoutingTool, prompt: str):
        self._llm = llm
        self._routing_tool = routing_tool
        self._prompt = prompt
    
    @property
    def route(self) -> Optional[str]:
        return self._routing_tool.route
    
    async def decide(self, context: str) -> str:
        llm_with_tools = self._llm.bind_tools([self._routing_tool.select_route])
        messages = [
            {"role": "system", "content": self._prompt},
            {"role": "user", "content": context},
        ]
        response = await llm_with_tools.ainvoke(messages)
        
        if response.tool_calls:
            tool_call = response.tool_calls[0]
            await self._routing_tool.select_route(**tool_call["args"])
        
        return self._routing_tool.route
```

**LangGraph 集成**：
```python
from langgraph.graph import StateGraph

def route_decision(state):
    route = state["selected_route"]
    routing_map = {
        "earnings_deep_dive": "deep_analysis",
        "standard_summary": "quick_summary",
        "risk_alert": "risk_pipeline",
    }
    return routing_map.get(route, "handle_error")

graph.add_conditional_edges(
    "router",
    route_decision,
    {
        "deep_analysis": "detailed_review_agents",
        "quick_summary": "summary_generator",
        "risk_pipeline": "risk_assessment_agents",
        "handle_error": "error_handler",
    },
)
```

### 模式 3: Report Compiler（报告编译器）

**用途**：从对话历史提取结构化数据到 Pydantic 模型

```python
from pydantic import BaseModel
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from typing import List, Type

class ReportCompiler:
    """纯提取 - 无工具、无推理循环"""
    
    def __init__(self, llm: BaseChatModel, schema: Type[BaseModel], prompt: str):
        self._llm = llm
        self._schema = schema
        self._prompt = prompt
    
    async def compile(self, messages: List[BaseMessage]) -> BaseModel:
        structured_llm = self._llm.with_structured_output(self._schema)
        all_messages = [
            {"role": "system", "content": self._prompt},
        ] + messages
        return await structured_llm.ainvoke(all_messages)
```

**动态 Prompt 生成**（从 Pydantic Schema）：
```python
def build_extraction_prompt(schema: Type[BaseModel]) -> str:
    """从 Pydantic 模型自动生成提取 prompt"""
    schema_json = schema.model_json_schema()
    
    return f"""你是数据提取专家。从对话历史中提取信息到以下 JSON Schema：

{json.dumps(schema_json, indent=2)}

规则：
1. 只基于对话中的事实，不要编造
2. 缺失字段留 null，不要猜测
3. 严格遵循 schema 的类型和格式要求
"""
```

## 生产级 Agent 实现

### 完整示例：ReAct Agent with LangGraph

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import ToolNode
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage

# 1. 定义状态
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], "对话历史"]

# 2. 创建 LLM 和工具
llm = ChatOpenAI(model="gpt-4-turbo-preview", temperature=0)
tools = [search_transactions_tool, get_portfolio_tool, ...]
llm_with_tools = llm.bind_tools(tools)

# 3. 创建 Prompt
system_prompt = """你是金融助手。
- 简洁并引用具体数据
- 货币格式：$X,XXX.XX
- 提醒用户咨询专业人士"""

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    MessagesPlaceholder(variable_name="messages"),
])

# 4. 定义节点
async def call_agent(state: AgentState):
    formatted = prompt.format_messages(messages=state["messages"])
    response = await llm_with_tools.ainvoke(formatted)
    return {"messages": [response]}

def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END

# 5. 构建图
workflow = StateGraph(AgentState)
workflow.add_node("agent", call_agent)
workflow.add_node("tools", ToolNode(tools))
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue, {
    "tools": "tools",
    END: END
})
workflow.add_edge("tools", "agent")

# 6. 编译（带持久化）
memory = MemorySaver()
agent = workflow.compile(checkpointer=memory)

# 7. 调用
config = {"configurable": {"thread_id": "user_123"}}
result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": "这个月 groceries 花了多少？"}]},
    config=config
)
```

### 错误处理与重试

```python
from functools import wraps
import asyncio

def retry_with_backoff(max_retries=3, base_delay=1.0):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
            return None
        return wrapper
    return decorator

@retry_with_backoff(max_retries=3)
async def call_external_api(...):
    # 实现...
```

### 可观测性 (LangSmith)

```python
import os
from langsmith import Client

# 设置环境变量
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "your_api_key"
os.environ["LANGCHAIN_PROJECT"] = "my-agent"

# 自定义回调用于指标
from langchain_core.callbacks import BaseCallbackHandler

class MetricsCallback(BaseCallbackHandler):
    def __init__(self):
        self.start_time = None
        self.token_count = 0
    
    def on_llm_start(self, *args, **kwargs):
        self.start_time = asyncio.get_event_loop().time()
    
    def on_llm_end(self, response, *args, **kwargs):
        duration = asyncio.get_event_loop().time() - self.start_time
        print(f"LLM call completed in {duration:.2f}s")
    
    def on_llm_new_token(self, token: str, *args, **kwargs):
        self.token_count += 1

# 使用回调
metrics = MetricsCallback()
response = await chain.ainvoke(
    {"input": message},
    config={"callbacks": [metrics]}
)
```

## 常见陷阱与解决方案

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| Agent 循环调用工具 | 没有终止条件 | 添加 retry_count 限制，检测重复工具调用 |
| 工具返回数据过多 | 未限制结果数量 | 在工具内限制返回 20-50 条 |
| 路由决策不稳定 | Prompt 模糊 | 在 Router Prompt 中提供明确的路由标准和示例 |
| 结构化输出格式错误 | Schema 与 Prompt 不匹配 | 使用动态 Prompt 生成器，从 Pydantic 自动生成 |
| 上下文溢出 | 对话历史无限增长 | 实现消息修剪/摘要策略 |

## 记忆与持久化策略

### 短期记忆（对话内）
- 使用 LangGraph 的 `MemorySaver` 自动保存状态
- 支持中断/恢复（人工审核场景）

### 长期记忆（跨对话）
```python
from langgraph.checkpoint.postgres import PostgresSaver

# 生产环境使用外部存储
write_engine = create_async_engine("postgresql+asyncpg://...")
checkpointer = PostgresSaver(write_engine)
agent = workflow.compile(checkpointer=checkpointer)
```

### 消息修剪策略
```python
from langchain_core.messages import trim_messages

trimmed = trim_messages(
    messages,
    max_tokens=4000,
    strategy="last",
    token_counter=llm,
    include_system=True,
)
```

## 多 Agent 协作

```python
from langgraph.graph import StateGraph

# 创建子 Agent
researcher = create_researcher_agent()
analyst = create_analyst_agent()
writer = create_writer_agent()

# 编排工作流
workflow = StateGraph(AgentState)
workflow.add_node("research", researcher)
workflow.add_node("analyze", analyst)
workflow.add_node("write", writer)

workflow.set_entry_point("research")
workflow.add_edge("research", "analyze")
workflow.add_edge("analyze", "write")
workflow.add_edge("write", END)

app = workflow.compile()
```

## 参考资源

- **详细模式说明**: 见 `references/patterns.md`
- **工具设计模板**: 见 `references/tool-templates.md`
- **生产部署检查清单**: 见 `references/production-checklist.md`

## 快速开始检查清单

- [ ] 定义清晰的 AgentState（包含消息历史 + 必要元数据）
- [ ] 设计工具（详尽 docstring + 简洁签名 + 结构化返回）
- [ ] 选择合适的模式（Analyzer/Router/Compiler）
- [ ] 配置 LangGraph 图（节点 + 条件边）
- [ ] 添加持久化（MemorySaver 或外部存储）
- [ ] 实现错误处理（重试 + 超时）
- [ ] 配置可观测性（LangSmith 追踪）
- [ ] 测试边界情况（空输入、工具失败、循环检测）
