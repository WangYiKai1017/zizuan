# Knowledge Query Tool

<cite>
**Referenced Files in This Document**
- [knowledge_query_tool.py](file://src/tools/knowledge_query_tool.py)
- [knowledge_base_querier.py](file://src/services/knowledge_base_querier.py)
- [markdown_file_manager.py](file://src/storage/markdown_file_manager.py)
- [llm_service.py](file://src/services/llm_service.py)
- [memory_query_result.py](file://src/models/memory_query_result.py)
- [interview_agent.py](file://src/agents/interview_agent.py)
- [interview_session_agent.py](file://src/agents/interview_session_agent.py)
- [test_kb_tools.py](file://test_kb_tools.py)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)

## Introduction
KnowledgeQueryTool serves as a simplified interface for querying the knowledge base, wrapping KnowledgeBaseQuerier to provide a streamlined query method with automatic target path construction and result formatting. It integrates with MarkdownFileManager and LLMService to deliver formatted knowledge context for InterviewAgent and ResumeSession components, enabling intelligent conversation flow and knowledge base integration.

## Project Structure
The KnowledgeQueryTool resides in the tools layer alongside other specialized tools for memory management and caching. It depends on the knowledge base querying service and storage infrastructure.

```mermaid
graph TB
subgraph "Tools Layer"
KQT[KnowledgeQueryTool]
end
subgraph "Services Layer"
KBQ[KnowledgeBaseQuerier]
LLM[LLMService]
end
subgraph "Storage Layer"
MFM[MarkdownFileManager]
end
subgraph "Models Layer"
MQR[MemoryQueryResult]
end
subgraph "Agents Layer"
IA[InterviewAgent]
RSA[InterviewSessionAgent]
end
KQT --> KBQ
KQT --> MFM
KQT --> LLM
KBQ --> MFM
KBQ --> LLM
KBQ --> MQR
IA --> KQT
RSA --> KQT
```

**Diagram sources**
- [knowledge_query_tool.py:11-31](file://src/tools/knowledge_query_tool.py#L11-L31)
- [knowledge_base_querier.py:202-236](file://src/services/knowledge_base_querier.py#L202-L236)
- [interview_agent.py:58-61](file://src/agents/interview_agent.py#L58-L61)
- [interview_session_agent.py:95-104](file://src/agents/interview_session_agent.py#L95-L104)

**Section sources**
- [knowledge_query_tool.py:11-31](file://src/tools/knowledge_query_tool.py#L11-L31)
- [knowledge_base_querier.py:202-236](file://src/services/knowledge_base_querier.py#L202-L236)

## Core Components
KnowledgeQueryTool provides a focused interface for knowledge base queries with automatic path management and result formatting.

Key responsibilities:
- Encapsulates KnowledgeBaseQuerier for simplified usage
- Automatically constructs target_path using user_id
- Extracts query text from various input formats
- Formats diverse result types into unified string output
- Integrates with MarkdownFileManager and LLMService

**Section sources**
- [knowledge_query_tool.py:11-31](file://src/tools/knowledge_query_tool.py#L11-L31)
- [knowledge_query_tool.py:33-66](file://src/tools/knowledge_query_tool.py#L33-L66)

## Architecture Overview
The KnowledgeQueryTool operates as a facade over the KnowledgeBaseQuerier, providing a clean abstraction for knowledge base interactions while maintaining access to underlying storage and language model capabilities.

```mermaid
sequenceDiagram
participant Client as "Client Component"
participant Tool as "KnowledgeQueryTool"
participant Querier as "KnowledgeBaseQuerier"
participant FileManager as "MarkdownFileManager"
participant LLM as "LLMService"
participant Storage as "Knowledge Base"
Client->>Tool : query(user_id, query, max_iterations)
Tool->>Tool : extract query text
Tool->>Tool : construct target_path
Tool->>Querier : query(user_input, target_path, state)
Querier->>Querier : validate target_path
Querier->>Querier : build agent graph
Querier->>FileManager : list_files/read_file/search_content
Querier->>LLM : invoke with ReAct template
LLM->>Storage : retrieve context
Storage-->>LLM : document content
LLM-->>Querier : reasoning steps
Querier-->>Tool : MemoryQueryResult
Tool->>Tool : format result
Tool-->>Client : formatted string
Note over Tool,Storage : Automatic target_path construction<br/>using user_id ensures scoped queries
```

**Diagram sources**
- [knowledge_query_tool.py:33-66](file://src/tools/knowledge_query_tool.py#L33-L66)
- [knowledge_base_querier.py:257-373](file://src/services/knowledge_base_querier.py#L257-L373)
- [markdown_file_manager.py:475-528](file://src/storage/markdown_file_manager.py#L475-L528)

## Detailed Component Analysis

### KnowledgeQueryTool Class
The KnowledgeQueryTool class provides a simplified interface for knowledge base queries with automatic path management and result formatting.

```mermaid
classDiagram
class KnowledgeQueryTool {
-MarkdownFileManager file_manager
-KnowledgeBaseQuerier querier
+__init__(querier : KnowledgeBaseQuerier)
+query(user_id : str, query : Any, max_iterations : int) str
-_format_result(result : Any) str
}
class KnowledgeBaseQuerier {
-MarkdownFileManager file_manager
-LLMService llm_service
-KnowledgeBaseTools tools
+__init__(file_manager : MarkdownFileManager, llm_service : LLMService)
+query(user_input : str, target_path : str, state : SessionState) MemoryQueryResult
-_build_agent() AgentGraph
-_parse_final_answer(output : str) dict
-_build_memory_result(answer : dict) MemoryQueryResult
}
class MarkdownFileManager {
+base_path : Path
+list_files(directory : str, include_details : bool, recursive : bool) List[Dict]
+read_file(path : str) str
+search_files(keyword : str, directory : str, max_results : int) List[SearchResult]
+follow_links(relative_path : str, depth : int) List[LinkedContent]
}
class LLMService {
+_model : BaseChatModel
+_prompt_templates : Dict[str, PromptTemplate]
+invoke(prompt : str, system_prompt : str, history : List[Dict]) LLMCallResult
+invoke_with_template(template_name : str, variables : Dict) LLMCallResult
+invoke_structured(template_name : str, variables : Dict, output_model) tuple
}
class MemoryQueryResult {
+query : str
+entries : List[MemoryEntry]
+linked_content : List[LinkedContent]
+total_count : int
+has_results : bool
+get_top_entries(n : int) List[MemoryEntry]
+empty() MemoryQueryResult
}
KnowledgeQueryTool --> KnowledgeBaseQuerier : "uses"
KnowledgeQueryTool --> MarkdownFileManager : "creates"
KnowledgeQueryTool --> LLMService : "creates"
KnowledgeBaseQuerier --> MarkdownFileManager : "uses"
KnowledgeBaseQuerier --> LLMService : "uses"
KnowledgeBaseQuerier --> MemoryQueryResult : "returns"
```

**Diagram sources**
- [knowledge_query_tool.py:11-31](file://src/tools/knowledge_query_tool.py#L11-L31)
- [knowledge_base_querier.py:202-236](file://src/services/knowledge_base_querier.py#L202-L236)
- [markdown_file_manager.py:31-78](file://src/storage/markdown_file_manager.py#L31-L78)
- [llm_service.py:32-89](file://src/services/llm_service.py#L32-L89)
- [memory_query_result.py:23-50](file://src/models/memory_query_result.py#L23-L50)

#### Query Method Implementation
The query method handles input processing, target path construction, and result formatting:

```mermaid
flowchart TD
Start([Query Method Entry]) --> ValidateInput["Validate Input Parameters"]
ValidateInput --> ExtractText["Extract Query Text"]
ExtractText --> IsDict{"Is Dictionary?"}
IsDict --> |Yes| GetQueryText["Get query_text field"]
IsDict --> |No| ConvertToString["Convert to String"]
GetQueryText --> ConstructPath["Construct Target Path"]
ConvertToString --> ConstructPath
ConstructPath --> CallQuerier["Call KnowledgeBaseQuerier.query()"]
CallQuerier --> FormatResult["Format Result"]
FormatResult --> IsString{"Is String?"}
IsString --> |Yes| ReturnString["Return Original String"]
IsString --> |No| IsMemoryResult{"Has entries attribute?"}
IsMemoryResult --> |Yes| FormatEntries["Format Memory Entries"]
IsMemoryResult --> |No| IsDictResult{"Is Dictionary?"}
IsDictResult --> |Yes| GetContent["Get content field"]
IsDictResult --> |No| ToString["Convert to String"]
FormatEntries --> ReturnFormatted["Return Formatted String"]
GetContent --> ReturnFormatted
ToString --> ReturnFormatted
ReturnString --> End([Method Exit])
ReturnFormatted --> End
```

**Diagram sources**
- [knowledge_query_tool.py:33-66](file://src/tools/knowledge_query_tool.py#L33-L66)
- [knowledge_query_tool.py:68-81](file://src/tools/knowledge_query_tool.py#L68-L81)

#### Result Formatting Logic
The `_format_result` method handles different response types:

1. **String Results**: Returned unchanged
2. **MemoryQueryResult Objects**: Extract entries and format as "From source: content" pairs
3. **Dictionary Results**: Extract "content" field or fall back to string conversion
4. **Other Types**: Converted to string representation

**Section sources**
- [knowledge_query_tool.py:33-66](file://src/tools/knowledge_query_tool.py#L33-L66)
- [knowledge_query_tool.py:68-81](file://src/tools/knowledge_query_tool.py#L68-L81)

### Integration with InterviewAgent and ResumeSession
KnowledgeQueryTool integrates seamlessly with both InterviewAgent and InterviewSessionAgent for enhanced conversation flow.

```mermaid
sequenceDiagram
participant Session as "InterviewSessionAgent"
participant Agent as "InterviewAgent"
participant Tool as "KnowledgeQueryTool"
participant Cache as "MemoryCacheTool"
participant Querier as "KnowledgeBaseQuerier"
Note over Session : Resume Session Flow
Session->>Session : Build Resume Analysis Prompt
Session->>Tool : query(user_id, analysis_result, max_iterations)
Tool->>Querier : query(user_input, target_path, state)
Querier-->>Tool : MemoryQueryResult
Tool-->>Session : Formatted String
Session->>Cache : append_cache(session_id, content)
Note over Agent : Interview Flow
Agent->>Agent : Identify Key Information
Agent->>Cache : get_cache(session_id, query)
Cache-->>Agent : Cached Content or None
alt Cache Miss
Agent->>Tool : query(user_id, key_info, max_iterations)
Tool->>Querier : query(user_input, target_path, state)
Querier-->>Tool : MemoryQueryResult
Tool-->>Agent : Formatted String
Agent->>Cache : append_cache(session_id, content, tags)
end
```

**Diagram sources**
- [interview_session_agent.py:202-239](file://src/agents/interview_session_agent.py#L202-L239)
- [interview_agent.py:134-162](file://src/agents/interview_agent.py#L134-L162)

**Section sources**
- [interview_session_agent.py:202-239](file://src/agents/interview_session_agent.py#L202-L239)
- [interview_agent.py:134-162](file://src/agents/interview_agent.py#L134-L162)

### KnowledgeBaseQuerier Integration
The KnowledgeBaseQuerier provides the underlying ReAct agent framework with specialized tools for knowledge base exploration.

Key capabilities:
- **File System Tools**: List files, read files, search content, follow links
- **Path Management**: Safe path construction and validation
- **Exploration Tracking**: Visit history and suspected file marking
- **ReAct Pattern**: Thought → Action → Observation loop with LLM guidance

**Section sources**
- [knowledge_base_querier.py:17-196](file://src/services/knowledge_base_querier.py#L17-L196)
- [knowledge_base_querier.py:202-373](file://src/services/knowledge_base_querier.py#L202-L373)

## Dependency Analysis
The KnowledgeQueryTool maintains loose coupling through dependency injection and follows the principle of composition over inheritance.

```mermaid
graph TB
subgraph "External Dependencies"
LangChain[LangChain]
Pydantic[Pydantic]
AsyncIO[AsyncIO]
end
subgraph "Internal Dependencies"
KQT[KnowledgeQueryTool]
KBQ[KnowledgeBaseQuerier]
MFM[MarkdownFileManager]
LLM[LLMService]
MQR[MemoryQueryResult]
end
KQT --> KBQ
KQT --> MFM
KQT --> LLM
KBQ --> MFM
KBQ --> LLM
KBQ --> MQR
MFM --> Pydantic
LLM --> LangChain
LLM --> AsyncIO
classDef external fill:#fff,stroke:#333,stroke-width:1px;
class LangChain,Pydantic,AsyncIO external;
```

**Diagram sources**
- [knowledge_query_tool.py:4-6](file://src/tools/knowledge_query_tool.py#L4-L6)
- [knowledge_base_querier.py:2-12](file://src/services/knowledge_base_querier.py#L2-L12)
- [llm_service.py:7-13](file://src/services/llm_service.py#L7-L13)

**Section sources**
- [knowledge_query_tool.py:4-6](file://src/tools/knowledge_query_tool.py#L4-L6)
- [knowledge_base_querier.py:2-12](file://src/services/knowledge_base_querier.py#L2-L12)

## Performance Considerations
KnowledgeQueryTool implements several performance optimizations:

- **Automatic Target Path Scoping**: Ensures queries remain within user-specific directories, reducing unnecessary file system traversal
- **Result Caching**: Integrated with MemoryCacheTool to avoid redundant queries during conversation sessions
- **Asynchronous Operations**: Full async support for non-blocking I/O operations
- **Efficient Path Construction**: Uses os.path.join for safe and efficient path building
- **Result Formatting Optimization**: Minimal processing overhead with early string return for simple cases

Best practices for optimal performance:
- Use structured query dictionaries with "query_text" field for complex queries
- Leverage the built-in caching mechanism to avoid repeated identical queries
- Monitor token usage through LLMService statistics
- Consider max_iterations tuning based on query complexity

## Troubleshooting Guide
Common issues and solutions when using KnowledgeQueryTool:

### Path Construction Issues
- **Problem**: Queries not returning expected results
- **Cause**: Incorrect target_path construction
- **Solution**: Verify user_id format and ensure knowledge base directory structure exists

### Result Formatting Problems
- **Problem**: Unexpected result types or formatting issues
- **Cause**: Non-standard result objects from KnowledgeBaseQuerier
- **Solution**: Check MemoryQueryResult structure and ensure proper entry attributes

### Integration Issues
- **Problem**: KnowledgeQueryTool not recognized by agents
- **Cause**: Import path or initialization issues
- **Solution**: Verify imports and ensure proper dependency injection

**Section sources**
- [knowledge_query_tool.py:56-66](file://src/tools/knowledge_query_tool.py#L56-L66)
- [interview_agent.py:134-162](file://src/agents/interview_agent.py#L134-L162)

## Conclusion
KnowledgeQueryTool provides a crucial bridge between the knowledge base infrastructure and application components, offering simplified access to complex ReAct-based querying capabilities. Its role in the broader conversation flow is essential for maintaining contextual awareness and providing relevant historical information during interviews. The tool's design emphasizes simplicity, reliability, and performance while maintaining deep integration with the underlying knowledge base management system.

Through its integration with InterviewAgent and InterviewSessionAgent, KnowledgeQueryTool enables sophisticated conversation management that combines human-like dialogue with systematic knowledge base exploration, creating a powerful foundation for personalized interview experiences.