# Testing Infrastructure

<cite>
**Referenced Files in This Document**
- [_common.py](file://tests/integration/_common.py)
- [run_all.py](file://tests/integration/run_all.py)
- [test_interview_api.py](file://tests/integration/test_interview_api.py)
- [test_kb_organizer_api.py](file://tests/integration/test_kb_organizer_api.py)
- [test_biography_outline_api.py](file://tests/integration/test_biography_outline_api.py)
- [test_biography_writing_api.py](file://tests/integration/test_biography_writing_api.py)
- [test_llm_service.py](file://tests/test_llm_service.py)
- [test_memory_manager.py](file://tests/test_memory_manager.py)
- [test_memory_repository.py](file://tests/test_memory_repository.py)
- [test_markdown_file_manager.py](file://tests/test_markdown_file_manager.py)
- [test_session_state.py](file://tests/test_session_state.py)
- [test_session_manager.py](file://tests/test_service/test_session_manager.py)
- [test_sse_response.py](file://tests/test_service/test_sse_response.py)
- [test_file_routes.py](file://tests/test_service/test_file_routes.py)
- [test_core_services.py](file://test_core_services.py)
- [test_system_assembly.py](file://test_system_assembly.py)
- [verify_core_services.py](file://verify_core_services.py)
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
This document describes the testing infrastructure of the project, covering unit, integration, and standalone end-to-end tests. It explains how tests are organized, how they exercise APIs and services, and how to run them effectively. The testing stack includes:
- Unit tests using pytest with mocked external dependencies
- Integration tests that call the HTTP/SSE endpoints of agents
- Standalone integration runners that orchestrate multiple agent flows
- Verification and assembly-layer tests for core services and system components

## Project Structure
The testing layout is organized by functional area:
- tests/unit: pytest-based unit tests for services, models, and utilities
- tests/integration: HTTP/SSE integration tests for agents and shared helpers
- tests/test_service: service-layer tests for SSE, session management, and file routes
- top-level test scripts: quick verification and assembly tests

```mermaid
graph TB
subgraph "Unit Tests (pytest)"
U1["tests/test_llm_service.py"]
U2["tests/test_memory_manager.py"]
U3["tests/test_memory_repository.py"]
U4["tests/test_markdown_file_manager.py"]
U5["tests/test_session_state.py"]
U6["tests/test_service/test_session_manager.py"]
U7["tests/test_service/test_sse_response.py"]
U8["tests/test_service/test_file_routes.py"]
end
subgraph "Integration Tests"
I1["tests/integration/_common.py"]
I2["tests/integration/test_interview_api.py"]
I3["tests/integration/test_kb_organizer_api.py"]
I4["tests/integration/test_biography_outline_api.py"]
I5["tests/integration/test_biography_writing_api.py"]
I6["tests/integration/run_all.py"]
end
subgraph "Verification Scripts"
V1["test_core_services.py"]
V2["test_system_assembly.py"]
V3["verify_core_services.py"]
end
I1 --> I2
I1 --> I3
I1 --> I4
I1 --> I5
I6 --> I2
I6 --> I3
I6 --> I4
I6 --> I5
V1 --> V2
V1 --> V3
```

**Diagram sources**
- [test_llm_service.py:1-187](file://tests/test_llm_service.py#L1-L187)
- [test_memory_manager.py:1-249](file://tests/test_memory_manager.py#L1-L249)
- [test_memory_repository.py:1-325](file://tests/test_memory_repository.py#L1-L325)
- [test_markdown_file_manager.py:1-207](file://tests/test_markdown_file_manager.py#L1-L207)
- [test_session_state.py:1-143](file://tests/test_session_state.py#L1-L143)
- [test_session_manager.py:1-134](file://tests/test_service/test_session_manager.py#L1-L134)
- [test_sse_response.py:1-136](file://tests/test_service/test_sse_response.py#L1-L136)
- [test_file_routes.py:1-243](file://tests/test_service/test_file_routes.py#L1-L243)
- [_common.py:1-194](file://tests/integration/_common.py#L1-L194)
- [test_interview_api.py:1-217](file://tests/integration/test_interview_api.py#L1-L217)
- [test_kb_organizer_api.py:1-120](file://tests/integration/test_kb_organizer_api.py#L1-L120)
- [test_biography_outline_api.py:1-186](file://tests/integration/test_biography_outline_api.py#L1-L186)
- [test_biography_writing_api.py:1-166](file://tests/integration/test_biography_writing_api.py#L1-L166)
- [run_all.py:1-74](file://tests/integration/run_all.py#L1-L74)
- [test_core_services.py:1-164](file://test_core_services.py#L1-L164)
- [test_system_assembly.py:1-206](file://test_system_assembly.py#L1-L206)
- [verify_core_services.py:1-173](file://verify_core_services.py#L1-L173)

**Section sources**
- [test_llm_service.py:1-187](file://tests/test_llm_service.py#L1-L187)
- [test_memory_manager.py:1-249](file://tests/test_memory_manager.py#L1-L249)
- [test_memory_repository.py:1-325](file://tests/test_memory_repository.py#L1-L325)
- [test_markdown_file_manager.py:1-207](file://tests/test_markdown_file_manager.py#L1-L207)
- [test_session_state.py:1-143](file://tests/test_session_state.py#L1-L143)
- [test_session_manager.py:1-134](file://tests/test_service/test_session_manager.py#L1-L134)
- [test_sse_response.py:1-136](file://tests/test_service/test_sse_response.py#L1-L136)
- [test_file_routes.py:1-243](file://tests/test_service/test_file_routes.py#L1-L243)
- [_common.py:1-194](file://tests/integration/_common.py#L1-L194)
- [test_interview_api.py:1-217](file://tests/integration/test_interview_api.py#L1-L217)
- [test_kb_organizer_api.py:1-120](file://tests/integration/test_kb_organizer_api.py#L1-L120)
- [test_biography_outline_api.py:1-186](file://tests/integration/test_biography_outline_api.py#L1-L186)
- [test_biography_writing_api.py:1-166](file://tests/integration/test_biography_writing_api.py#L1-L166)
- [run_all.py:1-74](file://tests/integration/run_all.py#L1-L74)
- [test_core_services.py:1-164](file://test_core_services.py#L1-L164)
- [test_system_assembly.py:1-206](file://test_system_assembly.py#L1-L206)
- [verify_core_services.py:1-173](file://verify_core_services.py#L1-L173)

## Core Components
- Shared integration helpers: HTTP/SSE parsing, timeouts, logging, and summary reporting
- Agent integration tests: Interview, KB Organizer, Biography Outline, Biography Writing
- Unit tests: LLM service, memory manager/repository, markdown file manager, session state, SSE/emitter, session manager, file routes
- Verification scripts: Quick checks for core services and system assembly

Key capabilities:
- HTTP/SSE streaming consumption with robust parsing and event emission
- Mock-driven unit tests that avoid external LLM calls
- End-to-end integration flows for agent pipelines
- Service-layer validations for SSE formatting and session concurrency

**Section sources**
- [_common.py:1-194](file://tests/integration/_common.py#L1-L194)
- [test_interview_api.py:1-217](file://tests/integration/test_interview_api.py#L1-L217)
- [test_kb_organizer_api.py:1-120](file://tests/integration/test_kb_organizer_api.py#L1-L120)
- [test_biography_outline_api.py:1-186](file://tests/integration/test_biography_outline_api.py#L1-L186)
- [test_biography_writing_api.py:1-166](file://tests/integration/test_biography_writing_api.py#L1-L166)
- [test_llm_service.py:1-187](file://tests/test_llm_service.py#L1-L187)
- [test_memory_manager.py:1-249](file://tests/test_memory_manager.py#L1-L249)
- [test_memory_repository.py:1-325](file://tests/test_memory_repository.py#L1-L325)
- [test_markdown_file_manager.py:1-207](file://tests/test_markdown_file_manager.py#L1-L207)
- [test_session_state.py:1-143](file://tests/test_session_state.py#L1-L143)
- [test_session_manager.py:1-134](file://tests/test_service/test_session_manager.py#L1-L134)
- [test_sse_response.py:1-136](file://tests/test_service/test_sse_response.py#L1-L136)
- [test_file_routes.py:1-243](file://tests/test_service/test_file_routes.py#L1-L243)
- [test_core_services.py:1-164](file://test_core_services.py#L1-L164)
- [test_system_assembly.py:1-206](file://test_system_assembly.py#L1-L206)
- [verify_core_services.py:1-173](file://verify_core_services.py#L1-L173)

## Architecture Overview
The testing architecture separates concerns into layers:
- Unit layer: isolated tests for services and utilities, using mocks to stub external systems
- Integration layer: HTTP/SSE tests that exercise real endpoints and streams
- Verification layer: quick smoke checks for core services and system assembly

```mermaid
sequenceDiagram
participant Runner as "Integration Runner"
participant Common as "_common.py"
participant API as "Agent API"
participant SSE as "SSE Stream Parser"
Runner->>Common : Import helpers (BASE_URL, timeouts, sse_iter)
Runner->>API : POST /api/<agent>/start (SSE)
API-->>Runner : SSE events (session_started, agent_message, done)
Runner->>SSE : parse events
Runner->>API : POST /api/<agent>/message (SSE)
API-->>Runner : SSE events (agent_message, error, done)
Runner->>API : GET /api/<agent>/status/{user_id}/{session_id}
API-->>Runner : JSON status
Runner->>API : POST /api/<agent>/end
API-->>Runner : JSON {status, session_id}
Runner->>API : GET /api/<agent>/status (expect 404)
API-->>Runner : 404 Not Found
Runner->>Common : summarize(name, ok, failures)
```

**Diagram sources**
- [_common.py:1-194](file://tests/integration/_common.py#L1-L194)
- [test_interview_api.py:1-217](file://tests/integration/test_interview_api.py#L1-L217)
- [test_kb_organizer_api.py:1-120](file://tests/integration/test_kb_organizer_api.py#L1-L120)
- [test_biography_outline_api.py:1-186](file://tests/integration/test_biography_outline_api.py#L1-L186)
- [test_biography_writing_api.py:1-166](file://tests/integration/test_biography_writing_api.py#L1-L166)

## Detailed Component Analysis

### Integration Helpers and Utilities
- Provides BASE_URL resolution, timeouts, and SSE parsing
- Implements a robust SSE parser that handles line endings, comments, and partial chunks
- Offers logging helpers and a summary reporter for integration scripts

```mermaid
flowchart TD
Start(["Start SSE Parsing"]) --> SetEnc["Set UTF-8 encoding"]
SetEnc --> Iterate["Iterate chunks via iter_content"]
Iterate --> Normalize["Normalize CRLF to LF"]
Normalize --> Split["Split on '\\n\\n' into blocks"]
Split --> ParseBlock["_parse_sse_block()"]
ParseBlock --> Valid{"Valid event/data?"}
Valid --> |Yes| Yield["Yield (event_name, data_dict)"]
Valid --> |No| Continue["Ignore and continue"]
Yield --> Next["Next block"]
Continue --> Next
Next --> Done(["End"])
```

**Diagram sources**
- [_common.py:48-151](file://tests/integration/_common.py#L48-L151)

**Section sources**
- [_common.py:1-194](file://tests/integration/_common.py#L1-L194)

### Interview Agent Integration Test
- Exercises start, message, status, end, and post-end status endpoints
- Validates SSE event presence and session lifecycle
- Uses shared SSE parsing and logging utilities

```mermaid
sequenceDiagram
participant T as "test_interview_api.py"
participant C as "_common.py"
participant R as "HTTP Request"
participant S as "Server"
T->>R : POST /api/interview/start (capture session_id)
R->>S : Accept SSE
S-->>R : events : session_started, agent_message, done
R-->>T : events + session_id
T->>R : POST /api/interview/message
R->>S : Accept SSE
S-->>R : events : agent_message, error, done
R-->>T : events
T->>R : GET /api/interview/status/{user_id}/{session_id}
R->>S : GET
S-->>R : 200 JSON status
R-->>T : status
T->>R : POST /api/interview/end
R->>S : POST
S-->>R : 200 JSON {status, session_id}
R-->>T : end result
T->>R : GET /api/interview/status (404 expected)
R->>S : GET
S-->>R : 404 Not Found
R-->>T : 404
T->>C : summarize()
```

**Diagram sources**
- [test_interview_api.py:92-208](file://tests/integration/test_interview_api.py#L92-L208)
- [_common.py:1-194](file://tests/integration/_common.py#L1-L194)

**Section sources**
- [test_interview_api.py:1-217](file://tests/integration/test_interview_api.py#L1-L217)

### KB Organizer Agent Integration Test
- Exercises run and result retrieval endpoints
- Demonstrates SSE streaming and result validation

```mermaid
sequenceDiagram
participant T as "test_kb_organizer_api.py"
participant C as "_common.py"
participant R as "HTTP Request"
participant S as "Server"
T->>R : POST /api/kb-organizer/run (SSE)
R->>S : Accept SSE
S-->>R : events (stream)
R-->>T : events
T->>R : GET /api/kb-organizer/result/{user_id}
R->>S : GET
S-->>R : 200 JSON result
R-->>T : result
T->>C : summarize()
```

**Diagram sources**
- [test_kb_organizer_api.py:37-111](file://tests/integration/test_kb_organizer_api.py#L37-L111)
- [_common.py:1-194](file://tests/integration/_common.py#L1-L194)

**Section sources**
- [test_kb_organizer_api.py:1-120](file://tests/integration/test_kb_organizer_api.py#L1-L120)

### Biography Outline Agent Integration Test
- Exercises generation, retrieval, and chapter confirmation endpoints
- Handles optional confirm step when a draft chapter exists

```mermaid
sequenceDiagram
participant T as "test_biography_outline_api.py"
participant C as "_common.py"
participant R as "HTTP Request"
participant S as "Server"
T->>R : POST /api/biography/outline/generate (SSE)
R->>S : Accept SSE
S-->>R : events (stream)
R-->>T : events
T->>R : GET /api/biography/outline/{user_id}
R->>S : GET
S-->>R : 200 JSON outline
R-->>T : outline
T->>R : PUT /api/biography/outline/{user_id}/chapters/{id}/confirm (optional)
R->>S : PUT
S-->>R : 200 JSON confirmed
R-->>T : confirm result
T->>C : summarize()
```

**Diagram sources**
- [test_biography_outline_api.py:44-177](file://tests/integration/test_biography_outline_api.py#L44-L177)
- [_common.py:1-194](file://tests/integration/_common.py#L1-L194)

**Section sources**
- [test_biography_outline_api.py:1-186](file://tests/integration/test_biography_outline_api.py#L1-L186)

### Biography Writing Agent Integration Test
- Exercises run, chapters listing, and full biography retrieval endpoints
- Handles potential 404 for full biography when not yet generated

```mermaid
sequenceDiagram
participant T as "test_biography_writing_api.py"
participant C as "_common.py"
participant R as "HTTP Request"
participant S as "Server"
T->>R : POST /api/biography/writing/run (SSE)
R->>S : Accept SSE
S-->>R : events (chapter_* progress)
R-->>T : events
T->>R : GET /api/biography/writing/{user_id}/chapters
R->>S : GET
S-->>R : 200 JSON chapters
R-->>T : chapters
T->>R : GET /api/biography/writing/{user_id}/full
R->>S : GET
S-->>R : 200 JSON full or 404
R-->>T : full or 404
T->>C : summarize()
```

**Diagram sources**
- [test_biography_writing_api.py:43-157](file://tests/integration/test_biography_writing_api.py#L43-L157)
- [_common.py:1-194](file://tests/integration/_common.py#L1-L194)

**Section sources**
- [test_biography_writing_api.py:1-166](file://tests/integration/test_biography_writing_api.py#L1-L166)

### Integration Test Orchestration
- A runner that executes all agent integration tests in sequence
- Captures exit codes and prints a summary table

```mermaid
flowchart TD
Start(["Start run_all.py"]) --> Loop["For each script"]
Loop --> Exec["subprocess.run(script)"]
Exec --> RC["Capture returncode"]
RC --> Append["Append (name, rc, elapsed)"]
Append --> Next["Next script"]
Next --> |More| Loop
Next --> |Done| Summary["Print summary table"]
Summary --> Exit(["Exit overall = 0 if all pass"])
```

**Diagram sources**
- [run_all.py:30-69](file://tests/integration/run_all.py#L30-L69)

**Section sources**
- [run_all.py:1-74](file://tests/integration/run_all.py#L1-L74)

### Unit Tests: LLM Service
- Tests invoke, retry, structured output, and statistics
- Uses mocking to avoid external LLM calls

```mermaid
classDiagram
class TestLLMService {
+test_invoke_success()
+test_invoke_with_retry()
+test_invoke_with_template()
+test_invoke_structured()
+test_invoke_structured_parse_error()
+test_invoke_structured_with_code_block()
+test_get_stats()
+test_clear_history()
+test_load_prompt_templates()
+test_invoke_failure()
}
class LLMService {
+invoke()
+invoke_with_template()
+invoke_structured()
+get_stats()
+clear_history()
}
TestLLMService --> LLMService : "mock ChatOpenAI"
```

**Diagram sources**
- [test_llm_service.py:8-187](file://tests/test_llm_service.py#L8-L187)

**Section sources**
- [test_llm_service.py:1-187](file://tests/test_llm_service.py#L1-L187)

### Unit Tests: Memory Manager and Repository
- Tests organize_and_save, apply_summary, query_events, and session clearing
- Validates repository save/get/update and timeline updates
- Uses mocked LLMService and repository methods

```mermaid
classDiagram
class TestMemoryManager {
+test_organize_and_save()
+test_apply_summary()
+test_short_term_memory_management()
+test_query_events()
+test_clear_session()
+test_get_event()
+test_get_all_people_and_events()
}
class MemoryManager {
+organize_and_save()
+apply_summary()
+update_short_term()
+add_conversation_turn()
+get_recent_conversations()
+query_events()
+clear_session()
+get_event()
+get_all_people()
+get_all_events()
}
class TestMemoryRepository {
+test_save_event()
+test_save_person()
+test_get_event()
+test_get_person()
+test_update_timeline()
+test_short_term_memory()
+test_history_management()
+test_clear_short_term()
+test_query_events()
+test_profile_management()
+test_get_all_people_and_events()
+test_get_latest_conversation_records()
}
class MemoryRepository {
+save_event()
+save_person()
+get_event()
+get_person()
+update_timeline()
+update_short_term()
+add_to_history()
+get_history()
+clear_short_term()
+query_events()
+update_profile()
+get_all_people()
+get_all_events()
+get_latest_conversation_records()
}
TestMemoryManager --> MemoryManager
TestMemoryRepository --> MemoryRepository
```

**Diagram sources**
- [test_memory_manager.py:18-249](file://tests/test_memory_manager.py#L18-L249)
- [test_memory_repository.py:44-325](file://tests/test_memory_repository.py#L44-L325)

**Section sources**
- [test_memory_manager.py:1-249](file://tests/test_memory_manager.py#L1-L249)
- [test_memory_repository.py:1-325](file://tests/test_memory_repository.py#L1-L325)

### Unit Tests: Markdown File Manager
- Tests create/read/update, search, wiki-link extraction/resolution, and link following
- Validates file existence and metadata

```mermaid
classDiagram
class TestMarkdownFileManager {
+test_create_file()
+test_create_file_overwrite()
+test_read_file()
+test_read_nonexistent_file()
+test_update_file()
+test_update_nonexistent_file()
+test_update_file_append()
+test_append_section()
+test_search_files()
+test_search_files_case_insensitive()
+test_search_files_with_context()
+test_extract_wikilinks()
+test_extract_wikilinks_with_anchor()
+test_resolve_link()
+test_follow_links()
+test_follow_links_with_depth()
+test_list_files()
+test_file_exists()
+test_get_file_stats()
}
class MarkdownFileManager {
+create_file()
+read_file()
+update_file()
+search_files()
+extract_wikilinks()
+resolve_link()
+follow_links()
+list_files()
+file_exists()
+get_file_stats()
}
TestMarkdownFileManager --> MarkdownFileManager
```

**Diagram sources**
- [test_markdown_file_manager.py:7-207](file://tests/test_markdown_file_manager.py#L7-L207)

**Section sources**
- [test_markdown_file_manager.py:1-207](file://tests/test_markdown_file_manager.py#L1-L207)

### Unit Tests: Session State
- Tests creation, adding turns, coverage updates, pending questions, and summaries

```mermaid
classDiagram
class TestSessionState {
+test_create_session()
+test_add_turn()
+test_update_coverage()
+test_collect_events_people()
+test_pending_questions()
+test_to_summary()
+test_get_recent_history()
+test_update_from_emotion()
}
class SessionState {
+add_turn()
+update_coverage()
+mark_event_collected()
+mark_person_collected()
+push_pending_question()
+pop_pending_question()
+has_pending_questions()
+to_summary()
+get_recent_history()
+update_from_emotion()
}
TestSessionState --> SessionState
```

**Diagram sources**
- [test_session_state.py:7-143](file://tests/test_session_state.py#L7-L143)

**Section sources**
- [test_session_state.py:1-143](file://tests/test_session_state.py#L1-L143)

### Service Tests: Session Manager
- Tests mutual exclusivity and session acquisition/release semantics

```mermaid
sequenceDiagram
participant SM as "SessionManager"
participant T as "test_session_manager.py"
T->>SM : acquire(user, INTERVIEW)
SM-->>T : session_id
T->>SM : acquire(user, INTERVIEW) again
SM-->>T : same session_id
T->>SM : acquire(user, KB_ORGANIZER)
SM-->>T : raises SessionConflictError
T->>SM : release(user, session_id)
SM-->>T : True
T->>SM : acquire(user, KB_ORGANIZER)
SM-->>T : new session_id
```

**Diagram sources**
- [test_session_manager.py:16-134](file://tests/test_service/test_session_manager.py#L16-L134)

**Section sources**
- [test_session_manager.py:1-134](file://tests/test_service/test_session_manager.py#L1-L134)

### Service Tests: SSE Response Formatting
- Tests SSEEvent and SSEEmitter formatting, timestamps, and error emission

```mermaid
classDiagram
class TestSSEEvent {
+test_format_basic_event()
+test_format_chinese_content()
+test_format_preserves_all_fields()
}
class SSEEvent {
+format()
}
class TestSSEEmitter {
+test_emit_and_stream()
+test_emit_adds_timestamp()
+test_emit_preserves_existing_timestamp()
+test_emit_error()
+test_emit_after_done_ignored()
}
class SSEEmitter {
+emit()
+emit_done()
+emit_error()
+stream()
}
TestSSEEvent --> SSEEvent
TestSSEEmitter --> SSEEmitter
```

**Diagram sources**
- [test_sse_response.py:9-136](file://tests/test_service/test_sse_response.py#L9-L136)

**Section sources**
- [test_sse_response.py:1-136](file://tests/test_service/test_sse_response.py#L1-L136)

### Service Tests: File Routes
- Tests directory listing, file content retrieval, tree view, and error handling
- Validates content-type detection and path traversal protection

```mermaid
sequenceDiagram
participant TC as "TestClient"
participant F as "files router"
participant FS as "KB_BASE_PATH"
TC->>F : GET /api/files/{user_id}
F->>FS : list root
FS-->>F : items
F-->>TC : 200 JSON items
TC->>F : GET /api/files/{user_id}/{path}
F->>FS : read file or list dir
FS-->>F : content or items
F-->>TC : 200 JSON content or items
TC->>F : GET /api/files/{user_id}/tree
F->>FS : walk tree
FS-->>F : tree
F-->>TC : 200 JSON tree
TC->>F : GET /api/files/nonexistent
F-->>TC : 404 with error code
```

**Diagram sources**
- [test_file_routes.py:49-243](file://tests/test_service/test_file_routes.py#L49-L243)

**Section sources**
- [test_file_routes.py:1-243](file://tests/test_service/test_file_routes.py#L1-L243)

### Verification and Assembly Tests
- test_core_services.py: end-to-end async tests for emotion detector, knowledge base querier, and question generator
- test_system_assembly.py: tests event bus, content summarizer, and conversation orchestrator
- verify_core_services.py: structural verification without LLM calls

```mermaid
flowchart TD
V1["verify_core_services.py"] --> Imports["Verify imports and class existence"]
V1 --> Models["Verify models/enums"]
V1 --> Config["Verify LLMConfig and PromptTemplate"]
V2["test_core_services.py"] --> Emo["EmotionDetector async test"]
V2 --> KBQ["KnowledgeBaseQuerier async test"]
V2 --> QGen["QuestionGenerator async test"]
V3["test_system_assembly.py"] --> Bus["EventBus test"]
V3 --> Sum["ContentSummarizer test"]
V3 --> Orch["ConversationOrchestrator test"]
```

**Diagram sources**
- [verify_core_services.py:1-173](file://verify_core_services.py#L1-L173)
- [test_core_services.py:1-164](file://test_core_services.py#L1-L164)
- [test_system_assembly.py:1-206](file://test_system_assembly.py#L1-L206)

**Section sources**
- [verify_core_services.py:1-173](file://verify_core_services.py#L1-L173)
- [test_core_services.py:1-164](file://test_core_services.py#L1-L164)
- [test_system_assembly.py:1-206](file://test_system_assembly.py#L1-L206)

## Dependency Analysis
- Integration tests depend on shared helpers for HTTP/SSE handling and logging
- Unit tests rely on pytest fixtures and mocking to isolate components
- Service tests validate internal protocols and error handling
- Verification scripts depend on core module imports and basic instantiation

```mermaid
graph TB
subgraph "Integration"
IT1["test_interview_api.py"]
IT2["test_kb_organizer_api.py"]
IT3["test_biography_outline_api.py"]
IT4["test_biography_writing_api.py"]
IC["_common.py"]
end
subgraph "Unit"
UT1["test_llm_service.py"]
UT2["test_memory_manager.py"]
UT3["test_memory_repository.py"]
UT4["test_markdown_file_manager.py"]
UT5["test_session_state.py"]
end
subgraph "Service"
ST1["test_session_manager.py"]
ST2["test_sse_response.py"]
ST3["test_file_routes.py"]
end
subgraph "Verification"
VT1["verify_core_services.py"]
VT2["test_core_services.py"]
VT3["test_system_assembly.py"]
end
IT1 --> IC
IT2 --> IC
IT3 --> IC
IT4 --> IC
UT1 --> UT2
UT2 --> UT3
UT3 --> UT4
UT4 --> UT5
ST1 --> ST2
ST2 --> ST3
VT1 --> VT2
VT2 --> VT3
```

**Diagram sources**
- [test_interview_api.py:1-217](file://tests/integration/test_interview_api.py#L1-L217)
- [test_kb_organizer_api.py:1-120](file://tests/integration/test_kb_organizer_api.py#L1-L120)
- [test_biography_outline_api.py:1-186](file://tests/integration/test_biography_outline_api.py#L1-L186)
- [test_biography_writing_api.py:1-166](file://tests/integration/test_biography_writing_api.py#L1-L166)
- [_common.py:1-194](file://tests/integration/_common.py#L1-L194)
- [test_llm_service.py:1-187](file://tests/test_llm_service.py#L1-L187)
- [test_memory_manager.py:1-249](file://tests/test_memory_manager.py#L1-L249)
- [test_memory_repository.py:1-325](file://tests/test_memory_repository.py#L1-L325)
- [test_markdown_file_manager.py:1-207](file://tests/test_markdown_file_manager.py#L1-L207)
- [test_session_state.py:1-143](file://tests/test_session_state.py#L1-L143)
- [test_session_manager.py:1-134](file://tests/test_service/test_session_manager.py#L1-L134)
- [test_sse_response.py:1-136](file://tests/test_service/test_sse_response.py#L1-L136)
- [test_file_routes.py:1-243](file://tests/test_service/test_file_routes.py#L1-L243)
- [verify_core_services.py:1-173](file://verify_core_services.py#L1-L173)
- [test_core_services.py:1-164](file://test_core_services.py#L1-L164)
- [test_system_assembly.py:1-206](file://test_system_assembly.py#L1-L206)

**Section sources**
- [test_interview_api.py:1-217](file://tests/integration/test_interview_api.py#L1-L217)
- [test_kb_organizer_api.py:1-120](file://tests/integration/test_kb_organizer_api.py#L1-L120)
- [test_biography_outline_api.py:1-186](file://tests/integration/test_biography_outline_api.py#L1-L186)
- [test_biography_writing_api.py:1-166](file://tests/integration/test_biography_writing_api.py#L1-L166)
- [_common.py:1-194](file://tests/integration/_common.py#L1-L194)
- [test_llm_service.py:1-187](file://tests/test_llm_service.py#L1-L187)
- [test_memory_manager.py:1-249](file://tests/test_memory_manager.py#L1-L249)
- [test_memory_repository.py:1-325](file://tests/test_memory_repository.py#L1-L325)
- [test_markdown_file_manager.py:1-207](file://tests/test_markdown_file_manager.py#L1-L207)
- [test_session_state.py:1-143](file://tests/test_session_state.py#L1-L143)
- [test_session_manager.py:1-134](file://tests/test_service/test_session_manager.py#L1-L134)
- [test_sse_response.py:1-136](file://tests/test_service/test_sse_response.py#L1-L136)
- [test_file_routes.py:1-243](file://tests/test_service/test_file_routes.py#L1-L243)
- [verify_core_services.py:1-173](file://verify_core_services.py#L1-L173)
- [test_core_services.py:1-164](file://test_core_services.py#L1-L164)
- [test_system_assembly.py:1-206](file://test_system_assembly.py#L1-L206)

## Performance Considerations
- Integration tests use generous timeouts for SSE reads to accommodate slower agent executions
- Unit tests minimize external I/O via mocking, enabling fast local iteration
- SSE parsing avoids line-buffering pitfalls by reading byte-by-byte and normalizing line endings
- Service-layer tests validate streaming semantics without heavy network overhead

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and remedies:
- Missing requests dependency in integration helpers: install the requests package to run integration tests
- No session_id captured from SSE: verify server-side session initialization and event emission
- SSE stream ends without "done": check server-side completion logic and ensure done event is emitted
- 404 after end: expected behavior; indicates session cleanup
- LLM invocation failures: mock ChatOpenAI in unit tests to avoid API calls
- Path traversal errors: ensure paths are validated and normalized before file access
- Session conflicts: release active sessions before acquiring a different agent type for the same user

**Section sources**
- [_common.py:12-20](file://tests/integration/_common.py#L12-L20)
- [test_interview_api.py:103-110](file://tests/integration/test_interview_api.py#L103-L110)
- [test_llm_service.py:180-187](file://tests/test_llm_service.py#L180-L187)
- [test_file_routes.py:218-238](file://tests/test_service/test_file_routes.py#L218-L238)
- [test_session_manager.py:39-58](file://tests/test_service/test_session_manager.py#L39-L58)

## Conclusion
The testing infrastructure combines robust unit tests with comprehensive integration tests that exercise HTTP/SSE endpoints. Shared helpers streamline SSE parsing and reporting, while verification scripts provide quick checks for core services and system assembly. The suite supports reliable development and regression detection across services, repositories, and agent pipelines.