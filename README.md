# 老人自传 Agent 系统

> 🤖 通过智能对话采访，帮助老人记录和传承人生故事

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 📖 项目简介

**老人自传 Agent 系统**是一个基于大语言模型的智能对话系统，通过与老人进行多轮友好的访谈，收集、整理和归纳人生经历，最终生成完整的自传文本。

### 核心价值

| 价值维度 | 说明 |
|----------|------|
| **传承价值** | 家族历史的载体，承载至少二代人的记忆 |
| **心理疗愈** | "人生回顾法"是重要的老年心理治疗方法，提升自我效能感 |
| **自我实现** | 重新赋予生命价值和意义，为过去的人事物赋予新解读 |
| **家庭和谐** | 子女通过自传理解父母的生命历程，增加彼此对话 |

> 💡 **核心理念**：对老年人来说，写回忆录的价值不仅来自最终的文稿，更来自撰写过程得到的**耐心倾听**。

---

## 🏗️ 系统架构

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

### 核心模块

- **问答引导层 Agent**：通过智能对话引导用户回忆，按人生阶段（童年、青年、中年、老年）系统采集信息
- **结构化整理层**：从对话中抽取人物、事件、心态等信息，构建结构化数据
- **记忆管理层**：多层记忆库存储事件、人物、时间线等数据，支持语义检索
- **写作生成层**：基于记忆库生成自传章节草稿

---

## ✨ 功能特性

### 核心能力

- 🎙️ **智能问答引导**：根据已采集内容自动生成下一问题，支持追问和确认
- 😊 **情绪识别与安抚**：实时识别用户情绪状态，智能调整对话策略
- 📚 **知识库管理**：自动整理对话内容，存储为结构化 Markdown 文件
- 🔍 **语义检索**：支持基于自然语言的记忆检索和交叉验证
- ✍️ **内容归纳**：自动归纳对话要点，提取关键人物和事件

### 问答策略

| 问题类型 | 说明 | 示例 |
|----------|------|------|
| 开放性问题 | 引导用户自由叙述 | "能讲讲您小时候的家是什么样的吗？" |
| 追问性问题 | 基于已回答深入挖掘 | "您提到父亲很严厉，具体体现在哪些方面？" |
| 确认性问题 | 核实关键信息 | "所以您是 1965 年出生在山东青岛，对吗？" |
| 情感性问题 | 引导情感表达 | "那时候您是什么感受？" |

---

## 🛠️ 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.10+ | 主要开发语言 |
| LangChain | 0.1.0+ | LLM 应用框架 |
| LangGraph | 0.0.20+ | Agent 状态机 |
| Pydantic | 2.0+ | 数据模型验证 |
| OpenAI | 1.0+ | 大语言模型接口 |
| Rich | 13.0+ | 美化终端输出 |
| Loguru | 0.7.0+ | 日志管理 |
| pytest | 7.0+ | 单元测试 |

---

## 📦 项目结构

```
elder-memoir-agent/
├── .env                      # 环境变量配置
├── .env.example              # 环境变量示例
├── .gitignore                # Git 忽略配置
├── .pre-commit-config.yaml   # pre-commit 配置
├── README.md                 # 项目说明文档
├── pyproject.toml            # 项目配置
├── requirements.txt          # 生产依赖
├── requirements-dev.txt      # 开发依赖
│
├── src/                      # 源代码目录
│   ├── __init__.py
│   ├── agents/               # Agent 模块
│   │   ├── __init__.py
│   │   ├── interview_agent.py           # 访谈 Agent
│   │   ├── interview_session_agent.py   # 访谈会话管理
│   │   └── profile_collection_agent.py  # 用户画像采集
│   ├── config/               # 配置模块
│   │   ├── __init__.py
│   │   ├── llm_config.py    # LLM 配置
│   │   └── profile_questions.py  # 画像问题库
│   ├── controllers/          # 控制器
│   │   ├── __init__.py
│   │   └── conversation_orchestrator.py  # 对话编排器
│   ├── core/                 # 核心模块
│   │   ├── event_bus.py    # 事件总线
│   │   └── conversation_orchestrator.py
│   ├── enums/               # 枚举类型
│   │   ├── emotion_type.py  # 情绪类型
│   │   ├── phase_type.py    # 人生阶段类型
│   │   ├── state_type.py    # 状态类型
│   │   └── strategy_type.py  # 策略类型
│   ├── models/               # 数据模型
│   │   ├── agent_response.py
│   │   ├── conversation_turn.py
│   │   ├── emotion_result.py
│   │   ├── event_info.py
│   │   ├── handoff_package.py
│   │   ├── memory_query_result.py
│   │   ├── organized_memory.py
│   │   ├── person_info.py
│   │   ├── session_state.py
│   │   └── summary_content.py
│   ├── prompts/             # Prompt 模板
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── emotion_prompts.py
│   │   ├── question_prompts.py
│   │   ├── summary_prompts.py
│   │   └── ContentSummarizer-Prompt.md
│   │   └── EmotionDetector-Prompt.md
│   │   └── KnowledgeBaseQuerier-Prompt.md
│   │   └── MemoryOrganizer-Prompt.md
│   │   └── QuestionGenerator-Prompt.md
│   ├── services/            # 服务模块
│   │   ├── __init__.py
│   │   ├── content_summarizer.py   # 内容归纳
│   │   ├── emotion_detector.py     # 情绪识别
│   │   ├── knowledge_base_querier.py  # 知识库查询(ReAct)
│   │   ├── llm_service.py          # LLM 统一服务
│   │   ├── memory_manager.py       # 记忆管理
│   │   └── question_generator.py   # 问题生成
│   ├── storage/             # 存储层
│   │   ├── __init__.py
│   │   ├── markdown_file_manager.py  # Markdown 文件管理
│   │   └── memory_repository.py      # 记忆仓库
│   ├── tools/               # 工具模块
│   │   ├── __init__.py
│   │   ├── knowledge_query_tool.py  # 知识查询工具
│   │   ├── memory_archive_tool.py   # 记忆归档工具
│   │   └── memory_cache_tool.py     # 记忆缓存工具
│   └── utils/               # 工具函数
│       ├── __init__.py
│       └── helpers.py
│
├── knowledge_base/           # 知识库（Markdown 文件系统）
│   ├── {user_id}/           # 用户目录
│   │   ├── events/          # 事件记录
│   │   │   ├── childhood/  # 童年时期
│   │   │   ├── youth/       # 青年时期
│   │   │   ├── middle_age/  # 中年时期
│   │   │   └── elderly/     # 老年时期
│   │   ├── people/          # 人物信息
│   │   │   ├── family/      # 家庭成员
│   │   │   └── others/      # 其他人物
│   │   └── timeline/        # 时间线
│   └── index.md            # 知识库索引
│
├── tests/                   # 测试目录
│   ├── __init__.py
│   ├── test_interview_session_agent.py
│   ├── test_llm_service.py
│   ├── test_markdown_file_manager.py
│   ├── test_memory_manager.py
│   ├── test_memory_repository.py
│   └── test_session_state.py
│
└── Prompts/                 # Prompt 文档
    ├── ContentSummarizer-Prompt.md
    ├── EmotionDetector-Prompt.md
    ├── KnowledgeBaseQuerier-Prompt.md
    ├── MemoryOrganizer-Prompt.md
    ├── ProfileCollection-Prompt.md
    ├── QuestionGenerator-Prompt.md
    └── SessionEndGuide-Prompt.md
```

---

## 🚀 快速开始

### 环境要求

- Python 3.10 或更高版本
- 支持的操作系统：macOS、Linux、Windows

### 1. 克隆项目

```bash
git clone <repository-url>
cd elder-memoir-agent
```

### 2. 创建虚拟环境

```bash
# 使用 venv
python -m venv .venv

# 激活虚拟环境
# Linux/macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 3. 安装依赖

```bash
# 安装生产依赖
pip install -r requirements.txt

# 安装开发依赖（可选）
pip install -r requirements-dev.txt
```

### 4. 配置环境变量

```bash
# 复制环境变量示例文件
cp .env.example .env

# 编辑 .env 文件，配置你的 API Key
# DEEPSEEK_APIKEY=your_api_key_here
```

`.env` 文件配置示例：

```bash
# LLM 配置
DEEPSEEK_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEEPSEEK_APIKEY=your_api_key_here
DEEPSEEK_MODEL_NAME=deepseek-v4-flash

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=logs/app.log

# 知识库配置
KNOWLEDGE_BASE_PATH=./knowledge_base
```

### 5. 运行测试

```bash
# 运行所有测试
pytest

# 运行测试并显示详细输出
pytest -v

# 运行测试并生成覆盖率报告
pytest --cov=src --cov-report=html
```

### 6. 代码质量检查

```bash
# 代码格式化
black src/

# 导入排序
isort src/

# 类型检查
mypy src/

# 代码检查
flake8 src/
```

---

## 📝 使用示例

### 基本使用

```python
from src.agents.interview_agent import InterviewAgent
from src.services.llm_service import LLMService

# 初始化 LLM 服务
llm_service = LLMService()

# 创建访谈 Agent
agent = InterviewAgent(llm_service=llm_service, user_id="test_user")

# 开始对话
response = agent.process_message("您好，我是来帮您记录人生故事的。")
print(response.content)

# 用户回复
response = agent.process_message("我叫张大爷，1935年出生在山东青岛。")
print(response.content)
```

### 知识库查询

```python
from src.services.knowledge_base_querier import KnowledgeBaseQuerier

querier = KnowledgeBaseQuerier(user_id="test_user")
result = querier.query("用户童年时期发生过什么重要的事情？")
print(result.answer)
print(f"相关事件: {result.related_events}")
```

---

## 📂 知识库结构

知识库采用 Markdown 文件系统存储，每个用户有独立的目录结构：

```
knowledge_base/
└── {user_id}/
    ├── index.md                    # 用户索引
    ├── events/
    │   ├── childhood/              # 童年事件
    │   ├── youth/                   # 青年事件
    │   ├── middle_age/              # 中年事件
    │   └── elderly/                 # 老年事件
    ├── people/
    │   ├── family/                 # 家庭成员
    │   │   ├── 父亲.md
    │   │   ├── 母亲.md
    │   │   └── ...
    │   └── others/                  # 其他人物
    │       ├── 老师.md
    │       ├── 朋友.md
    │       └── ...
    └── timeline/
        └── life-events.md          # 人生时间线
```

---

## 🔧 配置说明

### LLM 模型配置

支持配置不同的 LLM 提供商：

```python
# 使用 DeepSeek
LLMService(
    model="deepseek-v4-flash",
    api_key="your_key",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 使用 OpenAI
LLMService(
    model="gpt-4",
    api_key="your_key",
    base_url="https://api.openai.com/v1"
)
```

### 知识库配置

```bash
# 设置知识库根目录
KNOWLEDGE_BASE_PATH=./knowledge_base

# 或使用绝对路径
KNOWLEDGE_BASE_PATH=/data/knowledge_base
```

---

## 🧪 开发指南

### 添加新的服务

1. 在 `src/services/` 目录下创建新的服务文件
2. 继承基础服务类并实现相应接口
3. 在 `src/services/__init__.py` 中导出
4. 编写单元测试并确保通过

### 添加新的 Prompt

1. 在 `src/prompts/` 目录或 `Prompts/` 目录创建 Markdown 文件
2. 使用 Jinja2 模板语法定义变量占位符
3. 在服务代码中加载并使用 Prompt

### 开发流程

```bash
# 1. 创建功能分支
git checkout -b feature/your-feature

# 2. 编写代码
# ... 编辑代码 ...

# 3. 运行测试
pytest

# 4. 代码格式化
black src/
isort src/

# 5. 类型检查
mypy src/

# 6. 提交代码
git add .
git commit -m "feat: 添加新功能"
```

---

## 📚 相关文档

- [系统架构设计文档](./问答引导层Agent-系统架构设计.md)
- [详细设计文档](./问答引导层Agent-详细设计.md)
- [协作架构文档](./老人自传%20Agent%20协作架构.md)
- [自传写作指南](./老人自传写作指南.md)
- [记忆交互指南](./MEMORY_INTERACTION_GUIDE.md)
- [Prompt 文档目录](./Prompts/)

---

## ⚠️ 注意事项

### 隐私保护

- 所有用户数据存储在本地，请妥善保管
- 敏感信息请在 `.env` 中配置，不要提交到版本控制
- 涉及他人隐私的内容需征得相关人员同意

### 真实性原则

- 自传内容应保持真实，不虚构、不夸大
- 所有生成的内容需老人确认
- AI 仅作为辅助工具，不替代真实记忆

### 心理关怀

- 注意老人讲述时的情绪变化
- 遇到敏感话题时允许跳过
- 必要时提醒家属协助

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 🙏 致谢

感谢所有为项目做出贡献的开发者！

---

*让每一位老人的故事都被倾听和铭记*
