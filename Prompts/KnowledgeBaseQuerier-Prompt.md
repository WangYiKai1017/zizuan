# KnowledgeBaseQuerier 动态 Prompt 模板（ReAct 模式）

> 模板名称：`knowledge_base_react`  
> 职责：以 ReAct 模式动态查询知识库  
> 版本：v1.0  
> 日期：2026-04-19

---

## 一、设计理念

### 为什么使用 ReAct 模式？

传统的知识库查询方式是：
1. 提取关键词 → 2. 匹配搜索 → 3. 返回结果

这种方式的问题：
- 关键词可能提取不准
- 无法理解查询意图
- 无法动态探索关联内容

**ReAct 模式**（Reasoning + Acting）让大模型：
1. **理解意图**：分析用户输入，推断需要查询什么
2. **动态决策**：决定使用哪个工具、查什么、读什么
3. **迭代探索**：根据查询结果决定是否继续探索
4. **判断相关性**：最终判断哪些内容是相关的

---

## 二、Prompt 模板结构

```
## 系统角色

你是一个知识库查询助手，负责从一个 Markdown 文件系统知识库中查找相关信息。你拥有文件查询工具，可以自主决定查询哪些文件、读取哪些内容。

## 任务说明

根据用户的输入和当前对话状态，在知识库中查找相关的记忆内容。你需要：
1. 理解用户输入中隐含的查询意图
2. 使用工具查询知识库
3. 根据查询结果判断是否需要继续探索
4. 最终返回相关的记忆上下文

## 输入信息

### 用户输入
{user_input}

### 可用工具
{available_tools}

## 工具使用规范

你可以使用以下工具：

### 1. list_files
列出知识库中的所有文件。

```
Action: list_files
Action Input: {"path": "可选的目录路径"}
```

返回：文件列表

### 2. read_file
读取指定文件的内容。

```
Action: read_file
Action Input: {"file_path": "文件路径"}
```

返回：文件内容

### 3. search_content
在所有文件中搜索包含关键词的内容。

```
Action: search_content
Action Input: {"keyword": "搜索关键词", "limit": 结果数量}
```

返回：匹配的内容片段列表

### 4. follow_links
追踪文件中的 Wiki 链接，获取关联文件内容。

```
Action: follow_links
Action Input: {"file_path": "文件路径", "depth": 链接深度}
```

返回：关联文件内容列表

## ReAct 循环

你需要按照 Thought → Action → Observation 的循环进行：

```
Thought: 分析当前情况，决定下一步行动
Action: 选择工具并执行
Action Input: 工具参数
Observation: [系统返回结果]
```

循环直到你认为已经找到足够的信息，然后输出最终答案。

## 最终输出格式

当你认为查询完成时，输出：

```
Final Answer:
{
  "query_intent": "查询意图",
  "related_memories": [
    {
      "source": "来源文件路径",
      "content": "相关内容摘要",
      "relevance": "相关性说明",
      "memory_type": "long_term|profile"
    }
  ],
  "linked_context": [
    {
      "source": "来源",
      "target": "目标文件",
      "relation": "关联关系"
    }
  ],
  "search_summary": "搜索过程摘要"
}
```

## 注意事项

1. 不要盲目搜索，先理解用户意图
2. 每次行动前说明你的思考
3. 如果某个搜索没有结果，尝试换一个关键词
4. 注意追踪文件之间的链接关系
5. 最终只返回真正相关的内容，不要堆砌无关信息
```

---

## 三、动态变量说明

| 变量名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| `{user_input}` | string | ConversationTurn.user_input | 用户当前输入 |
| `{available_tools}` | string | 常量 | 工具列表的格式化描述 |

### available_tools 格式化

```python
def _get_available_tools_description() -> str:
    """获取工具列表描述"""
    return """
### 可用工具列表

1. **list_files** - 列出知识库文件
   - 参数: path (可选目录路径)
   - 返回: 文件路径列表

2. **read_file** - 读取文件内容
   - 参数: file_path (文件路径)
   - 返回: 文件内容

3. **search_content** - 全文搜索
   - 参数: keyword (关键词), limit (结果数量，默认10)
   - 返回: 匹配内容列表

4. **follow_links** - 追踪链接
   - 参数: file_path (文件路径), depth (链接深度，默认1)
   - 返回: 关联文件内容列表

### 知识库目录结构

```
knowledge_base/
├── events/          # 事件记录
├── people/          # 人物信息
├── timeline/        # 时间线
├── themes/          # 主题标签
└── summaries/       # 归纳摘要
```
"""
```

---

## 四、工具函数定义

### KnowledgeBaseQuerier 的工具函数

```python
# src/services/knowledge_base_querier.py
from langchain.tools import Tool
from typing import List, Dict, Any
import json

class KnowledgeBaseTools:
    """知识库查询工具集"""
    
    def __init__(self, file_manager: MarkdownFileManager):
        self.file_manager = file_manager
        self._tools = self._build_tools()
    
    def _build_tools(self) -> List[Tool]:
        """构建 LangChain 工具"""
        return [
            Tool(
                name="list_files",
                description="列出知识库中的所有文件",
                func=self._list_files,
            ),
            Tool(
                name="read_file",
                description="读取指定文件的内容",
                func=self._read_file,
            ),
            Tool(
                name="search_content",
                description="在所有文件中搜索包含关键词的内容",
                func=self._search_content,
            ),
            Tool(
                name="follow_links",
                description="追踪文件中的Wiki链接，获取关联文件内容",
                func=self._follow_links,
            ),
        ]
    
    def _list_files(self, args: str) -> str:
        """列出文件"""
        params = json.loads(args) if args else {}
        path = params.get("path", "")
        files = self.file_manager.list_files(path)
        return json.dumps(files, ensure_ascii=False, indent=2)
    
    def _read_file(self, args: str) -> str:
        """读取文件"""
        params = json.loads(args)
        file_path = params["file_path"]
        content = self.file_manager.read_file(file_path)
        return content[:2000]  # 限制长度
    
    def _search_content(self, args: str) -> str:
        """搜索内容"""
        params = json.loads(args)
        keyword = params["keyword"]
        limit = params.get("limit", 10)
        results = self.file_manager.search_files(keyword, limit)
        return json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2)
    
    def _follow_links(self, args: str) -> str:
        """追踪链接"""
        params = json.loads(args)
        file_path = params["file_path"]
        depth = params.get("depth", 1)
        links = self.file_manager.follow_links(file_path, depth)
        return json.dumps([l.to_dict() for l in links], ensure_ascii=False, indent=2)
    
    @property
    def tools(self) -> List[Tool]:
        return self._tools
```

---

## 五、ReAct Agent 实现

### KnowledgeBaseQuerier 核心代码

```python
# src/services/knowledge_base_querier.py
from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from typing import Optional
import logging

from services.llm_service import LLMService, get_llm_service
from storage.markdown_file_manager import MarkdownFileManager
from models import MemoryQueryResult, MemoryEntry, LinkedContent

logger = logging.getLogger(__name__)


class KnowledgeBaseQuerier:
    """
    知识库查询服务 - ReAct 模式
    
    职责：
    - 理解用户输入的查询意图
    - 使用 ReAct 模式动态查询知识库
    - 判断并返回相关的记忆上下文
    
    使用场景：
    - ConversationOrchestrator 每轮异步调用
    - QuestionGenerator 生成问题时参考
    """
    
    def __init__(
        self,
        file_manager: MarkdownFileManager,
        llm_service: LLMService = None,
    ):
        self.file_manager = file_manager
        self.llm_service = llm_service or get_llm_service()
        self.tools = KnowledgeBaseTools(file_manager)
        self.agent_executor = self._build_agent()
    
    def _build_agent(self) -> AgentExecutor:
        """构建 ReAct Agent"""
        # 获取 LangChain LLM
        llm = self.llm_service.get_langchain_llm()
        
        # ReAct Prompt
        prompt = PromptTemplate.from_template(
            self.llm_service.get_template("knowledge_base_react")["system_prompt"]
        )
        
        # 创建 Agent
        agent = create_react_agent(
            llm=llm,
            tools=self.tools.tools,
            prompt=prompt,
        )
        
        return AgentExecutor(
            agent=agent,
            tools=self.tools.tools,
            verbose=True,
            max_iterations=10,  # 最多10轮迭代
            handle_parsing_errors=True,
        )
    
    async def query(
        self,
        user_input: str,
        state: SessionState,
    ) -> MemoryQueryResult:
        """
        ReAct 模式查询知识库
        
        Args:
            user_input: 用户输入
            state: 会话状态
            
        Returns:
            MemoryQueryResult: 经过 LLM 判断的相关记忆
        """
        try:
            # 执行 ReAct Agent
            result = await self.agent_executor.ainvoke({
                "user_input": user_input,
                "available_tools": self._get_tools_description(),
            })
            
            # 解析最终答案
            final_answer = self._parse_final_answer(result["output"])
            
            return self._build_memory_result(final_answer)
            
        except Exception as e:
            logger.error(f"Knowledge base query failed: {e}")
            return MemoryQueryResult.empty()
    
    def _parse_final_answer(self, output: str) -> dict:
        """解析 Final Answer"""
        # 从输出中提取 JSON
        import re
        match = re.search(r"Final Answer:\s*(\{.*\})", output, re.DOTALL)
        if match:
            import json
            return json.loads(match.group(1))
        return {}
    
    def _build_memory_result(self, answer: dict) -> MemoryQueryResult:
        """构建 MemoryQueryResult"""
        entries = []
        for mem in answer.get("related_memories", []):
            entries.append(MemoryEntry(
                source=mem.get("source", ""),
                content=mem.get("content", ""),
                relevance=0.9,  # LLM 已判断相关性
                memory_type=mem.get("memory_type", "long_term"),
                metadata={"relevance_note": mem.get("relevance", "")},
            ))
        
        linked = []
        for link in answer.get("linked_context", []):
            linked.append(LinkedContent(
                source=link.get("source", ""),
                target=link.get("target", ""),
                relation=link.get("relation", ""),
                content_preview="",
            ))
        
        return MemoryQueryResult(
            query=answer.get("query_intent", ""),
            entries=entries,
            linked_content=linked,
            total_count=len(entries),
            has_results=len(entries) > 0,
        )
```

---

## 六、ReAct 执行示例

### 示例对话

```
用户输入：我记得小时候住在一个小院子里，有一棵枣树...

Thought: 用户提到童年的小院和枣树，我需要查找是否有相关的记录。我应该搜索"枣树"、"小院"或者"童年"相关的内容。
Action: search_content
Action Input: {"keyword": "枣树", "limit": 5}

Observation: [
  {"file_path": "events/童年记忆.md", "matched_text": "院子里有一棵大枣树...", "relevance": 0.95},
  {"file_path": "people/父亲.md", "matched_text": "父亲常在枣树下乘凉...", "relevance": 0.8}
]

Thought: 找到了两个相关文件。我应该读取这些文件获取更多上下文。
Action: read_file
Action Input: {"file_path": "events/童年记忆.md"}

Observation: # 童年记忆

## 小院
小时候住在一个小院子里，院子里有一棵大枣树。每到秋天，我们兄弟姐妹就盼着枣子熟...

Thought: 这个文件内容很相关。我还应该查看父亲的记录，因为提到了父亲常在枣树下乘凉。
Action: read_file
Action Input: {"file_path": "people/父亲.md"}

Observation: # 父亲

## 基本信息
姓名：XXX
职业：农民

## 与枣树的记忆
父亲常在枣树下乘凉，给我们讲故事...

Thought: 我已经找到了相关的记忆。现在应该追踪这些文件中的链接，看看是否有更多关联信息。
Action: follow_links
Action Input: {"file_path": "events/童年记忆.md", "depth": 1}

Observation: [
  {"source": "events/童年记忆.md", "target": "people/父亲.md", "relation": "父亲常在枣树下"},
  {"source": "events/童年记忆.md", "target": "timeline/1960s.md", "relation": "童年时期"}
]

Thought: 我已经获取了足够的信息。现在可以输出最终答案了。

Final Answer:
{
  "query_intent": "查询用户童年时期关于小院和枣树的记忆",
  "related_memories": [
    {
      "source": "events/童年记忆.md",
      "content": "小时候住在一个小院子里，院子里有一棵大枣树。每到秋天，我们兄弟姐妹就盼着枣子熟",
      "relevance": "直接匹配用户描述的枣树和小院",
      "memory_type": "long_term"
    },
    {
      "source": "people/父亲.md",
      "content": "父亲常在枣树下乘凉，给我们讲故事",
      "relevance": "与枣树相关的人物记忆",
      "memory_type": "profile"
    }
  ],
  "linked_context": [
    {
      "source": "events/童年记忆.md",
      "target": "people/父亲.md",
      "relation": "父亲常在枣树下"
    },
    {
      "source": "events/童年记忆.md",
      "target": "timeline/1960s.md",
      "relation": "童年时期"
    }
  ],
  "search_summary": "通过搜索'枣树'找到两个相关文件，读取后发现与用户描述高度匹配，并追踪了关联链接"
}
```

---

## 七、输出数据结构

### MemoryQueryResult

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class MemoryEntry(BaseModel):
    source: str
    content: str
    relevance: float = Field(ge=0, le=1)
    memory_type: str  # short_term | long_term | profile
    metadata: Dict[str, Any] = Field(default_factory=dict)

class LinkedContent(BaseModel):
    source: str
    target: str
    relation: str
    content_preview: Optional[str] = None

class MemoryQueryResult(BaseModel):
    query: str
    entries: List[MemoryEntry] = Field(default_factory=list)
    linked_content: List[LinkedContent] = Field(default_factory=list)
    total_count: int = 0
    has_results: bool = False
    
    @classmethod
    def empty(cls) -> "MemoryQueryResult":
        return cls(query="", has_results=False)
    
    @classmethod
    def from_entries(cls, query: str, entries: List[MemoryEntry]) -> "MemoryQueryResult":
        return cls(
            query=query,
            entries=entries,
            total_count=len(entries),
            has_results=len(entries) > 0,
        )
```
