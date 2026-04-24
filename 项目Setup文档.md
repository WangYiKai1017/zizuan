# 老人自传 Agent 系统 - 项目 Setup 文档

> 版本：v1.0  
> 日期：2026-04-19  
> 适用开发工具：Trae IDE

---

## 一、项目概述

### 1.1 项目背景

本项目是一个老人自传创作 Agent 系统，通过与老人的对话采访，收集人生经历，最终生成自传文本。

### 1.2 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     老人自传 Agent 系统                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │  问答引导层     │  │  结构化整理层   │                  │
│  │  (Conversation) │→ │  (Structuring)  │                  │
│  └─────────────────┘  └─────────────────┘                  │
│          ↓                    ↓                             │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │  记忆管理层     │  │  写作生成层     │                  │
│  │  (Memory)       │← │  (Writing)      │                  │
│  └─────────────────┘  └─────────────────┘                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

当前开发重点：**问答引导层 Agent**

### 1.3 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.10+ | 主要开发语言 |
| LangChain | 0.1.0+ | LLM 应用框架 |
| LangGraph | 0.0.20+ | Agent 状态机 |
| Pydantic | 2.0+ | 数据模型验证 |
| AsyncIO | - | 异步编程 |
| pytest | 7.0+ | 单元测试 |

---

## 二、环境准备

### 2.1 Python 版本

确保 Python 版本 >= 3.10：

```bash
python --version
# Python 3.10.x 或更高
```

推荐使用 pyenv 管理 Python 版本：

```bash
# 安装 pyenv（如果未安装）
curl https://pyenv.run | bash

# 安装 Python 3.10
pyenv install 3.10.13

# 设置项目 Python 版本
pyenv local 3.10.13
```

### 2.2 虚拟环境

创建并激活虚拟环境：

```bash
# 使用 venv
python -m venv .venv

# 激活（Linux/macOS）
source .venv/bin/activate

# 激活（Windows）
.venv\Scripts\activate
```

### 2.3 依赖安装

```bash
# 安装所有依赖
pip install -r requirements.txt

# 如果使用开发依赖
pip install -r requirements-dev.txt
```

---

## 三、依赖清单

### 3.1 requirements.txt

```
# 核心框架
langchain>=0.1.0
langgraph>=0.0.20
pydantic>=2.0.0

# LLM 相关
openai>=1.0.0
langchain-openai>=0.0.5

# 异步支持
aiofiles>=23.0.0
httpx>=0.25.0

# 工具类
python-dotenv>=1.0.0
pyyaml>=6.0
rich>=13.0.0  # 美化终端输出

# 日志
loguru>=0.7.0

# 文件处理
watchdog>=3.0.0  # 文件监控
```

### 3.2 requirements-dev.txt

```
# 测试
pytest>=7.0.0
pytest-asyncio>=0.21.0
pytest-cov>=4.0.0

# 代码质量
black>=23.0.0
isort>=5.12.0
flake8>=6.0.0
mypy>=1.0.0

# pre-commit
pre-commit>=3.0.0
```

---

## 四、目录结构

### 4.1 完整目录树

```
elder-memoir-agent/
├── .env                      # 环境变量配置
├── .env.example              # 环境变量示例
├── .gitignore                # Git 忽略配置
├── .pre-commit-config.yaml   # pre-commit 配置
├── README.md                 # 项目说明
├── requirements.txt          # 生产依赖
├── requirements-dev.txt      # 开发依赖
├── pyproject.toml            # 项目配置
│
├── src/                      # 源代码目录
│   ├── __init__.py
│   │
│   ├── main.py               # 应用入口
│   ├── config.py             # 配置管理
│   │
│   ├── models/               # 数据模型
│   │   ├── __init__.py
│   │   ├── session_state.py
│   │   ├── conversation_turn.py
│   │   ├── emotion_result.py
│   │   ├── memory_query_result.py
│   │   ├── summary_content.py
│   │   └── handoff_package.py
│   │
│   ├── enums/                # 枚举类型
│   │   ├── __init__.py
│   │   ├── state_type.py
│   │   ├── phase_type.py
│   │   ├── strategy_type.py
│   │   └── emotion_type.py
│   │
│   ├── services/             # 服务对象
│   │   ├── __init__.py
│   │   ├── llm_service.py          # 大模型统一入口
│   │   ├── question_generator.py   # 问题生成
│   │   ├── emotion_detector.py     # 情绪识别
│   │   ├── knowledge_base_querier.py  # 知识库查询(ReAct)
│   │   ├── content_summarizer.py   # 内容归纳
│   │   └── memory_manager.py       # 记忆管理
│   │
│   ├── controllers/          # 控制器
│   │   ├── __init__.py
│   │   └── conversation_orchestrator.py
│   │
│   ├── storage/              # 存储层
│   │   ├── __init__.py
│   │   ├── memory_repository.py
│   │   └── markdown_file_manager.py
│   │
│   ├── prompts/              # Prompt 模板
│   │   ├── __init__.py
│   │   ├── templates.py
│   │   └── prompts/          # Prompt 文件
│   │       ├── emotion_detection.md
│   │       ├── question_generation.md
│   │       ├── knowledge_base_react.md
│   │       └── content_summarization.md
│   │
│   └── utils/                # 工具函数
│       ├── __init__.py
│       ├── logger.py
│       └── helpers.py
│
├── knowledge_base/           # 知识库（md文件系统）
│   ├── events/               # 事件记录
│   ├── people/               # 人物信息
│   ├── timeline/             # 时间线
│   ├── themes/               # 主题标签
│   └── summaries/            # 归纳摘要
│
├── tests/                    # 测试目录
│   ├── __init__.py
│   ├── conftest.py           # pytest 配置
│   ├── unit/                 # 单元测试
│   │   ├── test_models.py
│   │   ├── test_services.py
│   │   └── test_storage.py
│   └── integration/          # 集成测试
│       └── test_conversation.py
│
└── docs/                     # 文档目录
    ├── architecture/         # 架构文档
    ├── prompts/              # Prompt 文档
    └── development/          # 开发文档
```

---

## 五、初始化步骤

### 5.1 克隆项目

```bash
git clone <repository-url>
cd elder-memoir-agent
```

### 5.2 创建虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或 .venv\Scripts\activate  # Windows
```

### 5.3 安装依赖

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt  # 开发环境
```

### 5.4 配置环境变量

复制环境变量示例文件：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```bash
# .env
# LLM 配置
QWEN_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_APIKEY=sk-9fc4c0b9ed2f4135938a52c8d8b6368a

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=logs/app.log

# 知识库配置
KNOWLEDGE_BASE_PATH=./knowledge_base
```

### 5.5 创建知识库目录

```bash
mkdir -p knowledge_base/{events,people,timeline,themes,summaries}
```

### 5.6 初始化 Git Hooks

```bash
pre-commit install
```

### 5.7 验证安装

```bash
# 运行测试
pytest

# 检查代码风格
black --check src/
isort --check src/
flake8 src/
mypy src/
```

---

## 六、配置文件说明

### 6.1 pyproject.toml

```toml
[project]
name = "elder-memoir-agent"
version = "0.1.0"
description = "老人自传创作 Agent 系统"
authors = [{name = "Your Name", email = "your@email.com"}]
requires-python = ">=3.10"

[project.optional-dependencies]
dev = ["pytest", "black", "isort", "flake8", "mypy"]

[tool.black]
line-length = 88
target-version = ['py310']

[tool.isort]
profile = "black"
line_length = 88

[tool.mypy]
python_version = "3.10"
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### 6.2 .pre-commit-config.yaml

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.12.1
    hooks:
      - id: black

  - repo: https://github.com/pycqa/isort
    rev: 5.13.2
    hooks:
      - id: isort

  - repo: https://github.com/pycqa/flake8
    rev: 7.0.0
    hooks:
      - id: flake8

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
```

### 6.3 .gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
ENV/

# IDE
.idea/
.vscode/
*.swp
*.swo

# 环境变量
.env
.env.local

# 日志
logs/
*.log

# 测试
.coverage
htmlcov/
.pytest_cache/
.mypy_cache/

# 构建
dist/
build/
*.egg-info/
```

---

## 七、开发启动指南

### 7.1 开发流程

```bash
# 1. 创建新功能分支
git checkout -b feature/task-xxx

# 2. 编写代码
# ... 编辑 src/ 下的文件

# 3. 运行测试
pytest tests/

# 4. 代码格式化
black src/
isort src/

# 5. 类型检查
mypy src/

# 6. 提交代码
git add .
git commit -m "feat: 实现XXX功能"
```

### 7.2 快速启动脚本

创建 `scripts/dev.sh`：

```bash
#!/bin/bash
# 开发环境快速启动

# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 运行测试
pytest

# 启动应用
python src/main.py
```

### 7.3 运行应用

```bash
# 直接运行
python src/main.py

# 或使用 uvicorn（如果有 API）
uvicorn src.main:app --reload
```

---

## 八、开发顺序建议

按照依赖关系，建议按以下顺序开发：

### Phase 1: 基础设施
1. **Task-001**: 实现数据对象（models/ 和 enums/）
2. **Task-002**: 实现 LLMService（services/llm_service.py）
3. **Task-003**: 实现 MarkdownFileManager（storage/markdown_file_manager.py）

### Phase 2: 记忆管理
4. **Task-004**: 实现 MemoryRepository（storage/memory_repository.py）
5. **Task-005**: 实现 MemoryManager（services/memory_manager.py）

### Phase 3: 核心服务
6. **Task-006**: 实现 EmotionDetector（services/emotion_detector.py）
7. **Task-007**: 实现 KnowledgeBaseQuerier（services/knowledge_base_querier.py）- **ReAct 模式**
8. **Task-008**: 实现 QuestionGenerator（services/question_generator.py）

### Phase 4: 系统组装
9. **Task-009**: 实现 ContentSummarizer（services/content_summarizer.py）
10. **Task-010**: 实现 EventBus（utils/event_bus.py）
11. **Task-011**: 实现 ConversationOrchestrator（controllers/conversation_orchestrator.py）
12. **Task-012**: 实现 HandoffPackage（models/handoff_package.py）

---

## 九、常见问题

### Q1: 如何添加新的 Prompt 模板？

在 `src/prompts/prompts/` 目录下添加 `.md` 文件，然后在 `src/prompts/templates.py` 中注册。

### Q2: 如何切换 LLM 模型？

修改 `.env` 中的 `DEFAULT_MODEL` 变量，或在代码中指定：

```python
llm_service = LLMService(model="gpt-4-turbo-preview")
```

### Q3: 如何调试 ReAct Agent？

设置环境变量 `LANGCHAIN_VERBOSE=true` 或在代码中：

```python
agent_executor = AgentExecutor(..., verbose=True)
```

### Q4: 如何查看知识库查询过程？

KnowledgeBaseQuerier 使用 `verbose=True` 会输出 ReAct 循环的每一步。

---

## 十、参考文档

- [系统架构设计文档](./问答引导层Agent-系统架构设计.md)
- [详细设计文档](./问答引导层Agent-详细设计.md)
- [Prompt 文档目录](./Prompts/)
- [开发故事卡目录](./开发故事卡/)
