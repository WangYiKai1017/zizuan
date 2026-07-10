# 生产部署检查清单

## 部署前验证

### 功能测试

- [ ] **基本流程测试**：Agent 能正确处理典型用户请求
- [ ] **边界情况测试**：空输入、超长输入、特殊字符
- [ ] **工具失败测试**：模拟 API 超时、数据库连接失败
- [ ] **循环检测测试**：验证 retry_count 限制生效
- [ ] **多轮对话测试**：上下文正确传递，无信息丢失

### 性能测试

- [ ] **响应时间**：P95 < 5s（简单查询），P95 < 15s（复杂分析）
- [ ] **并发测试**：同时处理 10+ 请求无性能退化
- [ ] **内存使用**：长时间运行无内存泄漏
- [ ] **上下文管理**：长对话自动修剪，不超出模型限制

### 安全测试

- [ ] **注入攻击**：SQL 注入、Prompt 注入防护
- [ ] **权限验证**：用户只能访问自己的数据
- [ ] **敏感信息**：API 密钥、密码不泄露到日志
- [ ] **速率限制**：防止滥用（每用户/每分钟请求数限制）

---

## 可观测性配置

### LangSmith 追踪

```python
import os

# 环境变量配置
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "ls__your_api_key"
os.environ["LANGCHAIN_PROJECT"] = "my-production-agent"
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

# 可选：自定义标签
os.environ["LANGCHAIN_METADATA_ENV"] = "production"
os.environ["LANGCHAIN_METADATA_VERSION"] = "1.0.0"
```

### 自定义指标回调

```python
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from typing import Any, Dict, List
import time
import logging

logger = logging.getLogger(__name__)

class ProductionMetricsCallback(BaseCallbackHandler):
    """生产环境指标收集"""
    
    def __init__(self, user_id: str, session_id: str):
        self.user_id = user_id
        self.session_id = session_id
        self.start_time: float = 0
        self.token_counts: Dict[str, int] = {
            "prompt": 0,
            "completion": 0,
            "total": 0,
        }
        self.tool_calls: List[Dict] = []
        self.errors: List[Dict] = []
    
    def on_llm_start(self, serialized: Dict[str, Any], *args, **kwargs) -> None:
        self.start_time = time.time()
        logger.info(f"[LLM Start] user={self.user_id}, session={self.session_id}")
    
    def on_llm_end(self, response: LLMResult, *args, **kwargs) -> None:
        duration = time.time() - self.start_time
        
        # 提取 token 使用
        if response.llm_output and "token_usage" in response.llm_output:
            usage = response.llm_output["token_usage"]
            self.token_counts["prompt"] = usage.get("prompt_tokens", 0)
            self.token_counts["completion"] = usage.get("completion_tokens", 0)
            self.token_counts["total"] = usage.get("total_tokens", 0)
        
        logger.info(
            f"[LLM End] duration={duration:.2f}s, "
            f"tokens={self.token_counts['total']}, "
            f"user={self.user_id}"
        )
        
        # 发送到监控系统（如 Prometheus, Datadog）
        self._emit_metrics(duration)
    
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, *args, **kwargs) -> None:
        self.tool_calls.append({
            "tool": serialized.get("name", "unknown"),
            "input": input_str[:200],  # 截断避免日志过大
            "timestamp": time.time(),
        })
        logger.info(f"[Tool Start] {serialized.get('name')}")
    
    def on_tool_end(self, output: str, *args, **kwargs) -> None:
        if self.tool_calls:
            self.tool_calls[-1]["output"] = output[:200]
            self.tool_calls[-1]["duration"] = time.time() - self.tool_calls[-1]["timestamp"]
        logger.info(f"[Tool End]")
    
    def on_chain_error(self, error: Exception, *args, **kwargs) -> None:
        self.errors.append({
            "error_type": type(error).__name__,
            "message": str(error)[:500],
            "timestamp": time.time(),
        })
        logger.error(f"[Chain Error] {type(error).__name__}: {error}")
    
    def _emit_metrics(self, duration: float) -> None:
        """发送到监控系统"""
        # 示例：Prometheus
        # METRIC_LLM_DURATION.observe(duration)
        # METRIC_LLM_TOKENS.labels(type="total").inc(self.token_counts["total"])
        # METRIC_TOOL_CALLS.inc(len(self.tool_calls))
        pass


# 使用方式
from langchain_core.callbacks import CallbackManager

callback_manager = CallbackManager([
    ProductionMetricsCallback(user_id="user_123", session_id="session_456")
])

response = await agent.ainvoke(
    {"messages": [...]},
    config={"callbacks": callback_manager}
)
```

---

## 错误处理策略

### 分级错误处理

```python
from enum import Enum
from typing import Optional, Dict, Any

class ErrorSeverity(Enum):
    INFO = "info"           # 可恢复，用户无感知
    WARNING = "warning"     # 可恢复，需记录
    ERROR = "error"         # 部分失败，需通知用户
    CRITICAL = "critical"   # 完全失败，需告警

class ErrorHandler:
    """统一错误处理器"""
    
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self.retry_delays = [1.0, 2.0, 4.0]  # 指数退避
    
    async def handle(
        self,
        func,
        *args,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        fallback: Optional[Any] = None,
        **kwargs,
    ) -> Any:
        """执行函数并处理错误"""
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_error = e
                
                # 记录错误
                self._log_error(e, attempt, severity)
                
                # 判断是否重试
                if not self._should_retry(e, attempt):
                    break
                
                # 等待后重试
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delays[attempt])
        
        # 所有重试失败
        return await self._on_final_failure(last_error, severity, fallback)
    
    def _should_retry(self, error: Exception, attempt: int) -> bool:
        """判断是否应该重试"""
        if attempt >= self.max_retries - 1:
            return False
        
        # 不重试的错误类型
        no_retry_errors = (
            ValueError,      # 参数错误
            TypeError,       # 类型错误
            PermissionError, # 权限错误
        )
        
        if isinstance(error, no_retry_errors):
            return False
        
        # 重试的错误类型
        retry_errors = (
            TimeoutError,
            ConnectionError,
            httpx.HTTPStatusError,
        )
        
        if isinstance(error, retry_errors):
            return True
        
        # 默认重试
        return True
    
    def _log_error(self, error: Exception, attempt: int, severity: ErrorSeverity) -> None:
        """记录错误"""
        log_func = {
            ErrorSeverity.INFO: logging.info,
            ErrorSeverity.WARNING: logging.warning,
            ErrorSeverity.ERROR: logging.error,
            ErrorSeverity.CRITICAL: logging.critical,
        }[severity]
        
        log_func(
            f"[Error] attempt={attempt + 1}/{self.max_retries}, "
            f"type={type(error).__name__}, "
            f"message={str(error)[:200]}"
        )
    
    async def _on_final_failure(
        self,
        error: Exception,
        severity: ErrorSeverity,
        fallback: Optional[Any],
    ) -> Any:
        """最终失败处理"""
        if fallback is not None:
            logging.warning(f"Using fallback value after final failure")
            return fallback
        
        if severity == ErrorSeverity.CRITICAL:
            # 发送告警
            await self._send_alert(error)
        
        raise error
    
    async def _send_alert(self, error: Exception) -> None:
        """发送告警（如 Slack、PagerDuty）"""
        # 实现告警逻辑
        pass
```

### 用户友好的错误消息

```python
ERROR_MESSAGES = {
    "timeout": "请求处理超时，请稍后重试",
    "rate_limit": "请求过于频繁，请稍后再试",
    "auth_failed": "认证失败，请检查您的登录状态",
    "data_not_found": "未找到相关数据，请尝试其他查询",
    "internal_error": "系统遇到意外错误，已记录并会尽快修复",
}

def get_user_friendly_error(error: Exception) -> str:
    """将技术错误转换为用户友好的消息"""
    if isinstance(error, TimeoutError):
        return ERROR_MESSAGES["timeout"]
    elif isinstance(error, PermissionError):
        return ERROR_MESSAGES["auth_failed"]
    elif isinstance(error, ValueError):
        if "not found" in str(error).lower():
            return ERROR_MESSAGES["data_not_found"]
    # 默认
    return ERROR_MESSAGES["internal_error"]
```

---

## 持久化配置

### 内存检查点（开发/测试）

```python
from langgraph.checkpoint.memory import MemorySaver

memory = MemorySaver()
agent = workflow.compile(checkpointer=memory)

# 使用
config = {"configurable": {"thread_id": "user_123_session_456"}}
result = await agent.ainvoke({...}, config=config)
```

### PostgreSQL 检查点（生产）

```python
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy.ext.asyncio import create_async_engine

# 创建异步引擎
write_engine = create_async_engine(
    "postgresql+asyncpg://user:password@localhost:5432/langgraph",
    pool_size=10,
    max_overflow=20,
)

# 创建检查点存储
checkpointer = PostgresSaver(write_engine)

# 编译 Agent
agent = workflow.compile(checkpointer=checkpointer)

# 初始化数据库表（首次部署时运行）
async with write_engine.begin() as conn:
    await conn.run_sync(checkpointer.setup)
```

### Redis 检查点（高性能场景）

```python
from langgraph.checkpoint.redis import RedisSaver

checkpointer = RedisSaver(
    redis_url="redis://localhost:6379",
    key_prefix="langgraph:",
)

agent = workflow.compile(checkpointer=checkpointer)
```

---

## 安全配置

### 环境变量管理

```python
# .env.example（不要提交真实值到版本控制）
OPENAI_API_KEY=sk-...
LANGCHAIN_API_KEY=ls__...
DATABASE_URL=postgresql://user:password@localhost/db
REDIS_URL=redis://localhost:6379
ENCRYPTION_KEY=your-32-byte-key

# config.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    openai_api_key: str
    langchain_api_key: str
    database_url: str
    redis_url: str
    encryption_key: str
    environment: str = "production"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

### 敏感数据加密

```python
from cryptography.fernet import Fernet
import base64
import hashlib

class SecureStorage:
    """敏感数据加密存储"""
    
    def __init__(self, key: str):
        # 从密钥派生 Fernet 密钥
        key_hash = hashlib.sha256(key.encode()).digest()
        key_base64 = base64.urlsafe_b64encode(key_hash)
        self._cipher = Fernet(key_base64)
    
    def encrypt(self, plaintext: str) -> str:
        """加密字符串"""
        return self._cipher.encrypt(plaintext.encode()).decode()
    
    def decrypt(self, ciphertext: str) -> str:
        """解密字符串"""
        return self._cipher.decrypt(ciphertext.encode()).decode()
    
    def store_api_key(self, user_id: str, api_key: str, db_session) -> None:
        """加密存储 API 密钥"""
        encrypted = self.encrypt(api_key)
        # 存储到数据库
        # db_session.execute(...)
    
    def retrieve_api_key(self, user_id: str, db_session) -> str:
        """解密读取 API 密钥"""
        # 从数据库读取
        # encrypted = ...
        return self.decrypt(encrypted)
```

---

## 部署架构

### 推荐架构

```
┌─────────────────┐     ┌──────────────────┐
│   Load Balancer │────▶│  App Server(s)   │
│   (nginx/ALB)   │     │  (FastAPI + UV)  │
└─────────────────┘     └────────┬─────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│   PostgreSQL    │   │     Redis       │   │   LangSmith     │
│  (Checkpoints)  │   │   (Cache/Queue) │   │  (Observability)│
└─────────────────┘   └─────────────────┘   └─────────────────┘
```

### Docker 部署示例

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 运行
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/langgraph
      - REDIS_URL=redis://redis:6379
    depends_on:
      - db
      - redis
  
  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=langgraph
    volumes:
      - postgres_data:/var/lib/postgresql/data
  
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

---

## 监控告警

### 关键指标

| 指标 | 告警阈值 | 说明 |
|------|----------|------|
| P95 响应时间 | > 10s | 用户体验下降 |
| 错误率 | > 5% | 系统异常 |
| Token 使用量 | 突增 50% | 可能滥用或攻击 |
| 活跃会话数 | > 预期 2x | 容量规划 |
| 工具调用失败率 | > 10% | 外部依赖问题 |

### Prometheus 配置示例

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'langgraph-agent'
    static_configs:
      - targets: ['app:8000']
    metrics_path: '/metrics'

# 告警规则
# alerting_rules.yml
groups:
  - name: agent_alerts
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status="500"}[5m]) > 0.05
        for: 5m
        annotations:
          summary: "High error rate detected"
      
      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 10
        for: 5m
        annotations:
          summary: "P95 latency above 10s"
```

---

## 上线检查清单

- [ ] 所有功能测试通过
- [ ] 性能测试达标
- [ ] 安全审计完成
- [ ] 监控告警配置完成
- [ ] 日志收集配置完成
- [ ] 备份策略配置完成
- [ ] 回滚方案测试通过
- [ ] 文档更新完成
- [ ] 团队培训完成
