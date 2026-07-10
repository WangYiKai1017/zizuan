# LangChain 工具设计模板

## 核心原则

### 1. Docstring 是 LLM 的"使用说明书"

**差的 Docstring**：
```python
@tool
def search_data(query: str) -> str:
    """搜索数据"""  # ❌ 太模糊，LLM 不知道何时使用
```

**好的 Docstring**：
```python
@tool
def search_transactions(
    keywords: str | None = None,
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """搜索金融交易记录。
    
    使用场景（当用户询问以下内容时调用此工具）：
    - 特定商户消费："我在星巴克花了多少钱？"
    - 分类消费统计："这个月 groceries 类别花了多少？"
    - 时间范围查询："上个月在餐饮上的总支出"
    - 组合查询："麦当劳的午餐消费"
    
    参数说明：
        keywords: 商户名称或描述关键词（如 "Starbucks", "McDonald's"）
        category: 消费分类（可选值：Groceries, Dining, Gas, Entertainment, Utilities）
        start_date: 开始日期（ISO 格式：YYYY-MM-DD）
        end_date: 结束日期（ISO 格式：YYYY-MM-DD）
    
    返回：
        字典包含：
        - transactions: 交易列表（最多 20 条）
        - total_amount: 总金额
        - count: 交易数量
        - summary: 自然语言摘要
    
    示例：
        search_transactions(keywords="Starbucks", category="Dining")
        → {"transactions": [...], "total_amount": 156.50, "count": 12, 
           "summary": "Found 12 transactions at Starbucks totaling $156.50"}
    """
```

### 2. 工厂函数模式（依赖注入）

当工具需要数据库连接、用户上下文等 LLM 无法提供的依赖时：

```python
from langchain_core.tools import tool
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

def create_search_transactions_tool(
    search_space_id: int,
    db_session: AsyncSession,
    user_id: str,
):
    """
    工厂函数：创建带有依赖注入的搜索工具
    
    为什么需要工厂函数？
    - LLM 只能提供语义参数（keywords, category）
    - 但工具需要技术依赖（db_session, user_id, search_space_id）
    - 工厂函数用闭包捕获技术依赖，暴露干净的接口给 LLM
    """
    
    @tool
    async def search_transactions(
        keywords: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        """搜索用户的金融交易记录。
        
        使用场景：
        - "我在 Amazon 花了多少钱？" → keywords="Amazon"
        - "这个月加油花了多少？" → category="Gas"
        - "上周的餐饮消费" → keywords + category 组合
        
        参数：
            keywords: 商户关键词（可选）
            category: 消费分类（可选）
            limit: 最大返回条数（默认 20，防止上下文溢出）
        
        返回：
            包含 transactions、total_amount、summary 的字典
        """
        # 实现：使用闭包中的 db_session 和 user_id
        query = select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.search_space_id == search_space_id,
        )
        
        if keywords:
            query = query.where(Transaction.description.ilike(f"%{keywords}%"))
        if category:
            query = query.where(Transaction.category == category)
        
        results = await db_session.execute(query.limit(limit))
        transactions = results.scalars().all()
        
        # 构建结构化返回
        total = sum(t.amount for t in transactions)
        return {
            "transactions": [
                {
                    "date": t.date.isoformat(),
                    "merchant": t.merchant,
                    "amount": t.amount,
                    "category": t.category,
                }
                for t in transactions
            ],
            "total_amount": total,
            "count": len(transactions),
            "summary": f"Found {len(transactions)} transactions totaling ${total:,.2f}",
        }
    
    return search_transactions


# 使用方式
tool = create_search_transactions_tool(
    search_space_id=123,
    db_session=db_session,
    user_id="user_456",
)
```

### 3. 返回结构化数据 + 预计算摘要

**差的返回**：
```python
@tool
def get_weather(location: str) -> str:
    return "Sunny, 72°F"  # ❌ LLM 需要自己解析
```

**好的返回**：
```python
@tool
def get_weather(location: str) -> dict:
    """获取指定地区的当前天气。
    
    参数：
        location: 城市名称（如 "San Francisco", "New York"）
    
    返回：
        字典包含：
        - temperature_f: 华氏温度
        - temperature_c: 摄氏温度
        - condition: 天气状况（Sunny, Cloudy, Rainy, etc.）
        - humidity: 湿度百分比
        - summary: 自然语言摘要
    """
    # 调用天气 API...
    return {
        "temperature_f": 72,
        "temperature_c": 22,
        "condition": "Sunny",
        "humidity": 45,
        "summary": "Sunny with a temperature of 72°F (22°C)",
    }
```

**为什么这样设计？**
- `temperature_f/c`：供需要精确数据的后续处理使用
- `summary`：LLM 可直接引用，减少解析负担
- 结构化字段：支持条件逻辑（如"如果温度>80°F，建议带水"）

### 4. 错误处理与超时

```python
from functools import wraps
import asyncio
from typing import Callable, Any

def tool_with_error_handling(
    max_retries: int = 2,
    timeout_seconds: float = 30.0,
):
    """工具装饰器：统一错误处理和超时"""
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            try:
                # 超时保护
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds,
                )
                return result
            except asyncio.TimeoutError:
                return {
                    "error": "timeout",
                    "message": f"Tool execution exceeded {timeout_seconds}s timeout",
                }
            except Exception as e:
                # 重试逻辑
                for attempt in range(max_retries):
                    try:
                        return await func(*args, **kwargs)
                    except Exception:
                        if attempt == max_retries - 1:
                            return {
                                "error": "execution_failed",
                                "message": str(e),
                                "tool_name": func.__name__,
                            }
                        await asyncio.sleep(0.5 * (attempt + 1))
        return wrapper
    return decorator


@tool
@tool_with_error_handling(max_retries=2, timeout_seconds=30.0)
async def fetch_external_api_data(endpoint: str) -> dict:
    """调用外部 API 获取数据。"""
    # 实现...
```

---

## 完整工具模板

### 模板 1: 数据库查询工具

```python
from langchain_core.tools import tool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta
from typing import Optional, List

def create_analytics_tool(db_session: AsyncSession, user_id: str):
    """创建数据分析工具"""
    
    @tool
    async def get_spending_by_category(
        period: str = "month",
        categories: Optional[List[str]] = None,
    ) -> dict:
        """按分类统计消费支出。
        
        使用场景：
        - "我这个月各分类花了多少钱？"
        - "对比上月和本月的餐饮支出"
        - "显示 Groceries 和 Dining 的支出占比"
        
        参数：
            period: 统计周期
                - "week": 最近 7 天
                - "month": 最近 30 天
                - "quarter": 最近 90 天
                - "year": 最近 365 天
            categories: 指定分类列表（可选，默认统计所有分类）
        
        返回：
            字典包含：
            - breakdown: 各分类支出明细 {category: amount}
            - total: 总支出
            - period_start: 统计开始日期
            - period_end: 统计结束日期
            - summary: 自然语言摘要
        """
        # 计算时间范围
        now = datetime.now()
        if period == "week":
            start = now - timedelta(days=7)
        elif period == "month":
            start = now - timedelta(days=30)
        elif period == "quarter":
            start = now - timedelta(days=90)
        else:  # year
            start = now - timedelta(days=365)
        
        # 构建查询
        query = (
            select(
                Transaction.category,
                func.sum(Transaction.amount).label("total"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.date >= start,
                Transaction.amount < 0,  # 支出为负
            )
            .group_by(Transaction.category)
        )
        
        if categories:
            query = query.where(Transaction.category.in_(categories))
        
        results = await db_session.execute(query)
        rows = results.all()
        
        # 构建返回
        breakdown = {row.category: abs(row.total) for row in rows}
        total = sum(breakdown.values())
        
        # 找出最大支出分类
        top_category = max(breakdown.items(), key=lambda x: x[1], default=(None, 0))
        
        return {
            "breakdown": breakdown,
            "total": total,
            "period_start": start.isoformat(),
            "period_end": now.isoformat(),
            "summary": (
                f"Total spending of ${total:,.2f} over the last {period}. "
                f"Top category: {top_category[0]} (${top_category[1]:,.2f})"
                if top_category[0]
                else f"Total spending of ${total:,.2f} over the last {period}."
            ),
        }
    
    return get_spending_by_category
```

### 模板 2: API 调用工具

```python
from langchain_core.tools import tool
import httpx
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class APIConfig(BaseModel):
    """API 配置模型"""
    base_url: str
    api_key: str
    timeout: float = 30.0
    max_retries: int = 2

def create_api_tool(config: APIConfig):
    """创建 API 调用工具"""
    
    @tool
    async def fetch_stock_price(
        symbol: str,
        include_history: bool = False,
        days: int = 30,
    ) -> dict:
        """获取股票价格和可选的历史数据。
        
        使用场景：
        - "AAPL 当前股价是多少？"
        - "显示特斯拉最近 30 天的股价走势"
        - "对比 NVDA 和 AMD 的价格"
        
        参数：
            symbol: 股票代码（如 "AAPL", "TSLA", "NVDA"）
            include_history: 是否包含历史数据（默认 False）
            days: 历史数据天数（仅当 include_history=True 时有效）
        
        返回：
            字典包含：
            - symbol: 股票代码
            - current_price: 当前价格
            - change_percent: 涨跌幅 (%)
            - market_cap: 市值
            - history: 历史价格列表（可选）
            - summary: 自然语言摘要
        """
        url = f"{config.base_url}/stocks/{symbol}"
        params = {"include_history": str(include_history).lower(), "days": days}
        headers = {"Authorization": f"Bearer {config.api_key}"}
        
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
        
        # 构建摘要
        change_direction = "up" if data["change_percent"] > 0 else "down"
        summary = (
            f"{data['symbol']} is trading at ${data['current_price']:.2f}, "
            f"{change_direction} {abs(data['change_percent']):.2f}% today. "
            f"Market cap: ${data['market_cap']:,}"
        )
        
        return {
            **data,
            "summary": summary,
        }
    
    return fetch_stock_price
```

### 模板 3: 文件操作工具

```python
from langchain_core.tools import tool
from pathlib import Path
from typing import Optional, List
import json

def create_file_tool(workspace_dir: str):
    """创建文件操作工具"""
    
    @tool
    async def read_document(
        path: str,
        max_lines: Optional[int] = None,
    ) -> dict:
        """读取文档内容。
        
        使用场景：
        - "读取 requirements.txt 看看依赖"
        - "显示 config.json 的内容"
        - "查看 README.md 的前 50 行"
        
        参数：
            path: 文件路径（相对于 workspace）
            max_lines: 最大读取行数（可选，防止大文件）
        
        返回：
            字典包含：
            - content: 文件内容
            - line_count: 总行数
            - truncated: 是否被截断
            - summary: 文件类型和大小摘要
        """
        full_path = Path(workspace_dir) / path
        
        if not full_path.exists():
            return {
                "error": "file_not_found",
                "message": f"File not found: {path}",
            }
        
        if not full_path.is_file():
            return {
                "error": "not_a_file",
                "message": f"Path is not a file: {path}",
            }
        
        try:
            content = full_path.read_text(encoding="utf-8")
            lines = content.split("\n")
            
            if max_lines and len(lines) > max_lines:
                content = "\n".join(lines[:max_lines])
                truncated = True
                content += f"\n\n... (truncated, {len(lines) - max_lines} more lines)"
            else:
                truncated = False
            
            return {
                "content": content,
                "line_count": len(lines),
                "truncated": truncated,
                "summary": f"{path} ({len(lines)} lines, {len(content)} chars)",
            }
        except UnicodeDecodeError:
            return {
                "error": "encoding_error",
                "message": f"Cannot read {path}: not a text file",
            }
    
    return read_document
```

---

## 工具测试清单

创建工具后，验证以下项目：

- [ ] **Docstring 清晰度**：第三方开发者能否仅凭 docstring 理解何时使用？
- [ ] **参数合理性**：所有参数都是 LLM 能提供的吗？需要工厂函数吗？
- [ ] **返回结构**：是否同时提供结构化数据和自然语言摘要？
- [ ] **结果限制**：列表返回是否限制了最大条数（20-50）？
- [ ] **错误处理**：超时、API 失败、文件不存在等情况是否优雅处理？
- [ ] **安全性**：是否有 SQL 注入、路径遍历等风险？
- [ ] **可观测性**：工具调用是否会被 LangSmith 追踪？

---

## 常见反模式

### ❌ 反模式 1: 模糊的 Docstring

```python
@tool
def process_data(data: str) -> str:
    """处理数据"""  # LLM: 这是什么数据？怎么处理？何时使用？
```

### ❌ 反模式 2: 返回原始数据无摘要

```python
@tool
def get_transactions() -> list:
    return [{"date": "...", "amount": 100}, ...]  # LLM 需要自己解析和总结
```

### ❌ 反模式 3: 无限制返回

```python
@tool
def search_all() -> list:
    return all_records  # 可能返回数万条，导致上下文溢出
```

### ❌ 反模式 4: 隐藏的错误

```python
@tool
def call_api() -> dict:
    response = requests.get(url)  # 可能抛出异常，LLM 无法处理
    return response.json()
```
