# Question Generator

<cite>
**Referenced Files in This Document**
- [question_generator.py](file://src/services/question_generator.py)
- [QuestionGenerator-Prompt.md](file://Prompts/QuestionGenerator-Prompt.md)
- [QuestionGenerator-Prompt.md](file://src/prompts/QuestionGenerator-Prompt.md)
- [interview_agent.py](file://src/agents/interview_agent.py)
- [interview_session_agent.py](file://src/agents/interview_session_agent.py)
- [knowledge_base_querier.py](file://src/services/knowledge_base_querier.py)
- [session_state.py](file://src/models/session_state.py)
- [phase_type.py](file://src/enums/phase_type.py)
- [emotion_type.py](file://src/enums/emotion_type.py)
- [conversation_turn.py](file://src/models/conversation_turn.py)
- [llm_service.py](file://src/services/llm_service.py)
- [knowledge_query_tool.py](file://src/tools/knowledge_query_tool.py)
- [memory_query_result.py](file://src/models/memory_query_result.py)
- [README.md](file://README.md)
</cite>

## Update Summary
**Changes Made**
- Updated QuestionGenerator.generate_next method to accept candidate questions and return structured QuestionResult objects
- Added new QuestionResult dataclass with JSON-formatted outputs including question text, source identification, and candidate question IDs
- Enhanced InterviewAgent integration to handle QuestionResult objects with source tracking
- Updated architecture diagrams to reflect the new structured output format
- Added documentation for candidate question selection and validation logic

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
The QuestionGenerator service is the adaptive question engine that powers the interview session orchestration. It transforms conversation history, user responses, and contextual memory into targeted follow-up questions while maintaining emotional sensitivity and chronological awareness. This document explains how the service analyzes conversation context, applies progressive disclosure patterns, targets time periods for chronological interviews, and integrates with InterviewAgent and KnowledgeBaseQuerier to deliver contextually relevant questions that balance guided interviewing with natural conversation flow.

**Updated** The service now provides structured QuestionResult objects with enhanced candidate question support and JSON-formatted outputs for improved integration and traceability.

## Project Structure
The QuestionGenerator resides in the services layer alongside other core services and integrates with agents, models, and tools across the system.

```mermaid
graph TB
subgraph "Services Layer"
QG["QuestionGenerator<br/>src/services/question_generator.py"]
KBQ["KnowledgeBaseQuerier<br/>src/services/knowledge_base_querier.py"]
LLM["LLMService<br/>src/services/llm_service.py"]
end
subgraph "Agents Layer"
IA["InterviewAgent<br/>src/agents/interview_agent.py"]
ISA["InterviewSessionAgent<br/>src/agents/interview_session_agent.py"]
end
subgraph "Models & Enums"
SS["SessionState<br/>src/models/session_state.py"]
PT["PhaseType<br/>src/enums/phase_type.py"]
ET["EmotionType<br/>src/enums/emotion_type.py"]
CT["ConversationTurn<br/>src/models/conversation_turn.py"]
MQR["MemoryQueryResult<br/>src/models/memory_query_result.py"]
QR["QuestionResult<br/>src/services/question_generator.py"]
end
subgraph "Tools"
KQT["KnowledgeQueryTool<br/>src/tools/knowledge_query_tool.py"]
end
subgraph "Prompts"
QGP["QuestionGenerator-Prompt.md<br/>Prompts/..."]
QGPSrc["QuestionGenerator-Prompt.md<br/>src/prompts/..."]
end
IA --> QG
ISA --> IA
IA --> KQT
KQT --> KBQ
KBQ --> LLM
QG --> LLM
QG --> SS
QG --> ET
QG --> PT
QG --> MQR
QG --> QR
IA --> SS
IA --> CT
QG --> QGP
QG --> QGPSrc
```

**Diagram sources**
- [question_generator.py:14-253](file://src/services/question_generator.py#L14-L253)
- [interview_agent.py:16-346](file://src/agents/interview_agent.py#L16-L346)
- [interview_session_agent.py:280-479](file://src/agents/interview_session_agent.py#L280-L479)
- [knowledge_base_querier.py:202-540](file://src/services/knowledge_base_querier.py#L202-L540)
- [llm_service.py:32-481](file://src/services/llm_service.py#L32-L481)
- [session_state.py:24-139](file://src/models/session_state.py#L24-L139)
- [phase_type.py:4-10](file://src/enums/phase_type.py#L4-L10)
- [emotion_type.py:4-50](file://src/enums/emotion_type.py#L4-L50)
- [conversation_turn.py:14-52](file://src/models/conversation_turn.py#L14-L52)
- [knowledge_query_tool.py:11-81](file://src/tools/knowledge_query_tool.py#L11-L81)
- [memory_query_result.py:23-81](file://src/models/memory_query_result.py#L23-L81)
- [QuestionGenerator-Prompt.md:1-352](file://Prompts/QuestionGenerator-Prompt.md#L1-L352)
- [QuestionGenerator-Prompt.md:1-352](file://src/prompts/QuestionGenerator-Prompt.md#L1-L352)

**Section sources**
- [README.md:27-53](file://README.md#L27-L53)
- [question_generator.py:14-253](file://src/services/question_generator.py#L14-L253)
- [interview_agent.py:16-346](file://src/agents/interview_agent.py#L16-L346)

## Core Components
- QuestionGenerator: Generates adaptive questions using a priority-driven decision chain, emotion-aware responses, and context-aware prompting.
- QuestionResult: Structured dataclass that encapsulates question text, source identification, and candidate question ID for enhanced traceability.
- InterviewAgent: Orchestrates the interview loop, invoking QuestionGenerator and integrating with KnowledgeBaseQuerier and MemoryCacheTool.
- InterviewSessionAgent: Manages the overall interview session lifecycle and coordinates between different interview phases.
- KnowledgeBaseQuerier: Implements a ReAct-style agent to search and retrieve relevant memory content for context-aware question generation.
- LLMService: Unified interface for prompt templating, structured outputs, and conversation history injection.
- SessionState: Tracks interview progress, phases, coverage, pending questions, and conversation history.
- EmotionType and PhaseType: Enumerations that inform question selection and stage transitions.
- MemoryQueryResult: Structured representation of retrieved memory entries and linked content.

**Updated** Added QuestionResult dataclass for structured question outputs and enhanced InterviewSessionAgent for session lifecycle management.

**Section sources**
- [question_generator.py:14-253](file://src/services/question_generator.py#L14-L253)
- [interview_agent.py:16-346](file://src/agents/interview_agent.py#L16-L346)
- [interview_session_agent.py:280-479](file://src/agents/interview_session_agent.py#L280-L479)
- [knowledge_base_querier.py:202-540](file://src/services/knowledge_base_querier.py#L202-L540)
- [llm_service.py:32-481](file://src/services/llm_service.py#L32-L481)
- [session_state.py:24-139](file://src/models/session_state.py#L24-L139)
- [emotion_type.py:4-50](file://src/enums/emotion_type.py#L4-L50)
- [phase_type.py:4-10](file://src/enums/phase_type.py#L4-L10)
- [memory_query_result.py:23-81](file://src/models/memory_query_result.py#L23-L81)

## Architecture Overview
The QuestionGenerator participates in a multi-stage interview pipeline with enhanced structured output support:
- InterviewAgent receives user input, identifies key information, queries knowledge base, updates cache, and asks the next question.
- QuestionGenerator evaluates emotion, pending questions, phase transitions, and memory context to produce the next question.
- LLMService loads dynamic prompt templates and injects conversation history for optimal engagement.
- KnowledgeBaseQuerier performs ReAct-style exploration within the user's knowledge base to enrich context.
- QuestionResult provides structured outputs with source tracking for candidate question selection.

```mermaid
sequenceDiagram
participant User as "User"
participant ISA as "InterviewSessionAgent"
participant IA as "InterviewAgent"
participant KQT as "KnowledgeQueryTool"
participant KBQ as "KnowledgeBaseQuerier"
participant QG as "QuestionGenerator"
participant LLM as "LLMService"
participant SS as "SessionState"
User->>ISA : "User input with candidate questions"
ISA->>IA : "Forward to InterviewAgent"
IA->>IA : "_identify_key_information(user_input)"
IA->>KQT : "query(user_id, key_info)"
KQT->>KBQ : "query(user_input, target_path, state)"
KBQ-->>KQT : "MemoryQueryResult"
KQT-->>IA : "Formatted memory context"
IA->>QG : "generate_next(user_input, memory_context, conversation_history, candidate_questions)"
QG->>SS : "Read current_phase, coverage, pending_questions"
QG->>LLM : "invoke_with_template('question_generation', variables)"
LLM-->>QG : "Structured question"
QG-->>IA : "QuestionResult"
IA-->>ISA : "QuestionResult"
ISA-->>User : "Question with source tracking"
```

**Updated** Enhanced sequence diagram to show the new QuestionResult-based architecture and candidate question integration.

**Diagram sources**
- [interview_agent.py:115-196](file://src/agents/interview_agent.py#L115-L196)
- [interview_session_agent.py:354-397](file://src/agents/interview_session_agent.py#L354-L397)
- [knowledge_query_tool.py:33-66](file://src/tools/knowledge_query_tool.py#L33-L66)
- [knowledge_base_querier.py:257-373](file://src/services/knowledge_base_querier.py#L257-L373)
- [question_generator.py:217-332](file://src/services/question_generator.py#L217-L332)
- [llm_service.py:293-325](file://src/services/llm_service.py#L293-L325)
- [session_state.py:24-139](file://src/models/session_state.py#L24-L139)

## Detailed Component Analysis

### QuestionGenerator: Adaptive Question Engine
The QuestionGenerator implements a priority-driven decision chain to select the most appropriate next question:
- Emotion response: If the user requires special handling, generate a supportive response before asking a new question.
- Pending questions: Serve pre-cached follow-ups to maintain momentum.
- Phase transition: When coverage reaches a threshold, propose a natural transition to the next life stage.
- Contextual question: Otherwise, generate a question informed by user input, memory context, strategy, and conversation history.

**Updated** Enhanced with new QuestionResult-based architecture and candidate question support.

Key behaviors:
- Emotion-aware fallbacks: Provides predefined responses for high-intensity negative emotions or fatigue.
- Progressive disclosure: Uses memory context to guide deeper exploration without overwhelming the user.
- Time period targeting: Leverages SessionState coverage thresholds to move from childhood to elderly stages systematically.
- Structured prompting: Uses a dedicated template to ensure consistent question types and reasoning.
- Candidate question integration: Supports selection and validation of candidate questions with ID tracking.

```mermaid
flowchart TD
Start(["Generate Next Question"]) --> CheckEmotion["Emotion needs special handling?"]
CheckEmotion --> |Yes| EmotionResp["Generate emotion response"]
CheckEmotion --> |No| CheckPending["Has pending questions?"]
CheckPending --> |Yes| ReturnPending["Return pending question"]
CheckPending --> |No| CheckPhase["Should change phase?"]
CheckPhase --> |Yes| Transition["Generate phase transition question"]
CheckPhase --> |No| CheckCandidate["Has candidate questions?"]
CheckCandidate --> |Yes| CandidateSelection["Select and validate candidate"]
CheckCandidate --> |No| Contextual["Generate contextual question"]
EmotionResp --> End(["Return QuestionResult"])
ReturnPending --> End
Transition --> End
CandidateSelection --> End
Contextual --> End
```

**Updated** Added candidate question selection flow to the decision tree.

**Diagram sources**
- [question_generator.py:38-74](file://src/services/question_generator.py#L38-L74)
- [question_generator.py:75-108](file://src/services/question_generator.py#L75-L108)
- [question_generator.py:109-140](file://src/services/question_generator.py#L109-L140)
- [question_generator.py:152-195](file://src/services/question_generator.py#L152-L195)
- [question_generator.py:217-332](file://src/services/question_generator.py#L217-L332)

**Section sources**
- [question_generator.py:14-332](file://src/services/question_generator.py#L14-L332)

### QuestionResult: Structured Question Output
The QuestionResult dataclass provides a standardized structure for question outputs with enhanced traceability and source tracking:

```python
@dataclass
class QuestionResult:
    """Result of generating the next interview question."""
    question: str
    source: str  # "generated" | "candidate_question"
    candidate_question_id: Optional[str] = None
```

**New** Key features:
- **question**: The final question text to be asked to the user
- **source**: Indicates whether the question was generated or selected from candidates
- **candidate_question_id**: Tracks the specific candidate question ID when applicable

Source validation and fallback mechanisms ensure robust operation even with malformed responses.

**Section sources**
- [question_generator.py:14-20](file://src/services/question_generator.py#L14-L20)

### QuestionGenerator-Prompt Template System
The QuestionGenerator-Prompt.md defines a structured template that guides the LLM to:
- Understand the user's recent input, current emotion, memory context, phase, strategy, and conversation history.
- Apply principles such as prioritizing emotion handling, using specificization, emotionalization, and association.
- Output a JSON object containing the question, question type, reasoning, and expected information categories.

**Updated** The new generate_next method uses a specialized prompt that incorporates candidate questions for enhanced interview guidance.

The LLMService loads this template dynamically and renders it with runtime variables, enabling consistent and context-aware question generation.

```mermaid
classDiagram
class QuestionGenerator {
+generate(user_input, emotion, memory, state) str
+generate_next(user_input, memory_context, conversation_history, candidate_questions) QuestionResult
-_generate_emotion_response(...)
-_generate_contextual_question(...)
-_should_change_phase(state) bool
-_get_phase_transition_question(state) str
-_get_default_question(phase) str
}
class QuestionResult {
+question : str
+source : str
+candidate_question_id : Optional[str]
}
class LLMService {
+invoke_with_template(template_name, variables, history) LLMCallResult
+invoke_structured(template_name, variables, output_model) (Model, LLMCallResult)
+invoke(prompt, history, response_format) LLMCallResult
+_load_prompt_templates()
}
class SessionState {
+current_phase
+coverage
+pending_questions
+conversation_history
}
class EmotionType {
<<enum>>
+NEUTRAL
+SADNESS
+CONFUSION
+FATIGUE
+RELUCTANCE
}
class PhaseType {
<<enum>>
+CHILDHOOD
+YOUTH
+YOUNG_ADULT
+MIDDLE_AGE
+ELDERLY
}
QuestionGenerator --> QuestionResult : "returns"
QuestionGenerator --> LLMService : "uses templates"
QuestionGenerator --> SessionState : "reads state"
QuestionGenerator --> EmotionType : "guides responses"
QuestionGenerator --> PhaseType : "drives transitions"
```

**Updated** Added QuestionResult class and enhanced LLMService invoke method signature.

**Diagram sources**
- [question_generator.py:14-332](file://src/services/question_generator.py#L14-L332)
- [llm_service.py:293-325](file://src/services/llm_service.py#L293-L325)
- [session_state.py:24-139](file://src/models/session_state.py#L24-L139)
- [emotion_type.py:4-50](file://src/enums/emotion_type.py#L4-L50)
- [phase_type.py:4-10](file://src/enums/phase_type.py#L4-L10)

**Section sources**
- [QuestionGenerator-Prompt.md:1-352](file://Prompts/QuestionGenerator-Prompt.md#L1-L352)
- [QuestionGenerator-Prompt.md:1-352](file://src/prompts/QuestionGenerator-Prompt.md#L1-L352)
- [llm_service.py:126-161](file://src/services/llm_service.py#L126-L161)

### Contextual Awareness and Progressive Disclosure
Contextual awareness is achieved through:
- Conversation history: Injected into LLMService calls to maintain continuity.
- Memory context: Formatted MemoryQueryResult entries guide deeper exploration.
- Strategy and phase: Interview strategy and current life phase influence question framing.
- Pending questions: Pre-specified follow-ups maintain engagement and momentum.
- Candidate questions: Structured candidate question lists provide guided interview paths.

**Updated** Enhanced with candidate question integration for improved interview flow control.

Progressive disclosure patterns:
- Start with broad, open-ended questions to establish comfort.
- Use follow-ups to drill down into specifics when users mention events or people.
- Introduce confirmatory questions to validate key facts.
- Transition naturally between phases when coverage thresholds are met.
- Select relevant candidate questions based on user responses for guided interviewing.

```mermaid
flowchart TD
Input["User Input"] --> Identify["Identify key entities"]
Identify --> CacheCheck{"Cached memory?"}
CacheCheck --> |Yes| UseCache["Use cached memory context"]
CacheCheck --> |No| QueryKB["Query KnowledgeBaseQuerier"]
QueryKB --> CacheUpdate["Update cache"]
UseCache --> BuildPrompt["Build contextual prompt"]
CacheUpdate --> BuildPrompt
BuildPrompt --> CandidateCheck{"Has candidate questions?"}
CandidateCheck --> |Yes| CandidateSelection["Select relevant candidate"]
CandidateCheck --> |No| Ask["Ask next question"]
CandidateSelection --> Ask
Ask --> Record["Record conversation turn"]
```

**Updated** Added candidate question selection flow to the processing pipeline.

**Diagram sources**
- [interview_agent.py:115-184](file://src/agents/interview_agent.py#L115-L184)
- [knowledge_query_tool.py:33-66](file://src/tools/knowledge_query_tool.py#L33-L66)
- [knowledge_base_querier.py:257-373](file://src/services/knowledge_base_querier.py#L257-L373)
- [question_generator.py:109-140](file://src/services/question_generator.py#L109-L140)
- [question_generator.py:217-332](file://src/services/question_generator.py#L217-L332)

**Section sources**
- [interview_agent.py:115-184](file://src/agents/interview_agent.py#L115-L184)
- [knowledge_query_tool.py:33-66](file://src/tools/knowledge_query_tool.py#L33-L66)
- [knowledge_base_querier.py:257-373](file://src/services/knowledge_base_querier.py#L257-L373)
- [question_generator.py:109-140](file://src/services/question_generator.py#L109-L140)
- [question_generator.py:217-332](file://src/services/question_generator.py#L217-L332)

### Time Period Targeting for Chronological Interviews
The QuestionGenerator enforces chronological progression by monitoring coverage thresholds per life phase:
- Coverage thresholds: When coverage for the current phase exceeds 80%, the system proposes a natural transition to the next phase.
- Phase ordering: Defined as Childhood → Youth → Young Adult → Middle Age → Elderly.
- Transition questions: Provide smooth bridges between phases, encouraging deeper exploration of the next stage.

```mermaid
flowchart TD
Current["Current Phase Coverage"] --> Threshold{"Coverage >= 80%?"}
Threshold --> |No| Continue["Continue exploring current phase"]
Threshold --> |Yes| NextPhase["Determine next phase"]
NextPhase --> TransitionQ["Generate transition question"]
Continue --> End(["Return"])
TransitionQ --> End
```

**Diagram sources**
- [question_generator.py:152-195](file://src/services/question_generator.py#L152-L195)
- [phase_type.py:4-10](file://src/enums/phase_type.py#L4-L10)

**Section sources**
- [question_generator.py:152-195](file://src/services/question_generator.py#L152-L195)
- [phase_type.py:4-10](file://src/enums/phase_type.py#L4-L10)

### Integration with InterviewAgent and KnowledgeBaseQuerier
InterviewAgent orchestrates the end-to-end interview loop with enhanced QuestionResult support:
- Starts the session and records turns.
- Identifies key information from user input to drive knowledge base queries.
- Queries KnowledgeBaseQuerier via KnowledgeQueryTool, caches results, and passes formatted memory context to QuestionGenerator.
- Handles QuestionResult objects with source tracking and candidate question ID preservation.
- Applies time warnings near session end and records assistant replies.

**Updated** Enhanced with QuestionResult handling and candidate question integration.

```mermaid
sequenceDiagram
participant ISA as "InterviewSessionAgent"
participant IA as "InterviewAgent"
participant KQT as "KnowledgeQueryTool"
participant KBQ as "KnowledgeBaseQuerier"
participant QG as "QuestionGenerator"
participant LLM as "LLMService"
ISA->>IA : "handle_input(user_input, candidate_questions)"
IA->>IA : "_identify_key_information(user_input)"
IA->>KQT : "query(user_id, key_info)"
KQT->>KBQ : "query(user_input, target_path, state)"
KBQ-->>KQT : "MemoryQueryResult"
KQT-->>IA : "Formatted memory context"
IA->>QG : "generate_next(user_input, memory_context, conversation_history, candidate_questions)"
QG->>LLM : "invoke_with_template('question_generation', variables)"
LLM-->>QG : "QuestionResult"
QG-->>IA : "QuestionResult"
IA->>IA : "Handle source tracking and time warnings"
IA-->>ISA : "QuestionResult"
ISA-->>ISA : "Process result and continue session"
```

**Updated** Enhanced sequence diagram to show QuestionResult-based communication and candidate question handling.

**Diagram sources**
- [interview_agent.py:115-196](file://src/agents/interview_agent.py#L115-L196)
- [interview_session_agent.py:354-397](file://src/agents/interview_session_agent.py#L354-L397)
- [knowledge_query_tool.py:33-66](file://src/tools/knowledge_query_tool.py#L33-L66)
- [knowledge_base_querier.py:257-373](file://src/services/knowledge_base_querier.py#L257-L373)
- [question_generator.py:217-332](file://src/services/question_generator.py#L217-L332)
- [llm_service.py:293-325](file://src/services/llm_service.py#L293-L325)

**Section sources**
- [interview_agent.py:115-196](file://src/agents/interview_agent.py#L115-L196)
- [interview_session_agent.py:354-397](file://src/agents/interview_session_agent.py#L354-L397)
- [knowledge_query_tool.py:33-66](file://src/tools/knowledge_query_tool.py#L33-L66)
- [knowledge_base_querier.py:257-373](file://src/services/knowledge_base_querier.py#L257-L373)
- [question_generator.py:217-332](file://src/services/question_generator.py#L217-L332)

### Conversation Turn Structure for Optimal Engagement
Each conversation turn captures:
- User input, agent response, extracted entities and events, emotion, referenced memory files, and metadata.
- SessionState maintains conversation history, coverage, and pending questions to inform QuestionGenerator decisions.
- QuestionResult provides structured tracking of question sources and candidate selections.

**Updated** Enhanced with QuestionResult integration for improved conversation tracking.

```mermaid
classDiagram
class ConversationTurn {
+int turn_id
+datetime timestamp
+string user_input
+string agent_response
+Entity[] extracted_entities
+EventInfo[] extracted_events
+string emotion
+string[] source_files_referenced
+dict metadata
}
class SessionState {
+string session_id
+datetime created_at
+datetime last_activity
+StateType current_state
+PhaseType current_phase
+StrategyType strategy
+int turn_count
+Dict~PhaseType,float~ coverage
+string[] collected_events
+string[] collected_people
+TopicInfo current_topic
+EmotionState emotion_state
+string[] pending_questions
+ConversationTurn[] conversation_history
+dict user_preferences
}
class QuestionResult {
+question : str
+source : str
+candidate_question_id : Optional[str]
}
SessionState "1" o-- "*" ConversationTurn : "contains"
```

**Updated** Added QuestionResult class to the conversation tracking structure.

**Diagram sources**
- [conversation_turn.py:14-52](file://src/models/conversation_turn.py#L14-L52)
- [session_state.py:24-139](file://src/models/session_state.py#L24-L139)
- [question_generator.py:14-20](file://src/services/question_generator.py#L14-L20)

**Section sources**
- [conversation_turn.py:14-52](file://src/models/conversation_turn.py#L14-L52)
- [session_state.py:24-139](file://src/models/session_state.py#L24-L139)
- [question_generator.py:14-20](file://src/services/question_generator.py#L14-L20)

### Question Generation Patterns, Timing Strategies, and Emotional Adaptation
Patterns:
- Open-ended questions to initiate storytelling.
- Follow-up questions to deepen details when users mention events or people.
- Confirmatory questions to validate key facts.
- Emotion response questions to acknowledge and soothe strong feelings.
- Candidate question selection to guide interview flow based on user responses.

**Updated** Added candidate question selection as a new pattern for guided interviewing.

Timing strategies:
- InterviewAgent tracks elapsed time and adds a gentle time warning near the session threshold.
- QuestionGenerator respects user energy by avoiding overly deep probing when fatigue or reluctance is detected.
- QuestionResult preserves source information for timing-aware question delivery.

Emotional adaptation:
- EmotionType enumerations guide QuestionGenerator's fallback responses for sadness, fatigue, and reluctance.
- Emotion-aware templates and structured outputs help the LLM tailor tone and phrasing to the user's emotional state.
- Candidate question selection considers user emotional state when choosing appropriate follow-up questions.

**Section sources**
- [emotion_type.py:4-50](file://src/enums/emotion_type.py#L4-L50)
- [question_generator.py:75-108](file://src/services/question_generator.py#L75-L108)
- [interview_agent.py:274-287](file://src/agents/interview_agent.py#L274-L287)
- [question_generator.py:217-332](file://src/services/question_generator.py#L217-L332)

## Dependency Analysis
The QuestionGenerator depends on:
- LLMService for prompt templating and structured outputs.
- SessionState for phase, coverage, and conversation history.
- EmotionType and PhaseType for decision-making.
- MemoryQueryResult for memory context formatting.
- InterviewAgent for orchestrating the interview loop and passing conversation history.
- QuestionResult for structured output representation.

**Updated** Enhanced dependency graph to include QuestionResult and InterviewSessionAgent.

```mermaid
graph TB
QG["QuestionGenerator"]
QR["QuestionResult"]
LLM["LLMService"]
SS["SessionState"]
ET["EmotionType"]
PT["PhaseType"]
MQR["MemoryQueryResult"]
IA["InterviewAgent"]
ISA["InterviewSessionAgent"]
QG --> QR
QG --> LLM
QG --> SS
QG --> ET
QG --> PT
QG --> MQR
IA --> QG
ISA --> IA
```

**Updated** Added QuestionResult and InterviewSessionAgent to the dependency structure.

**Diagram sources**
- [question_generator.py:14-332](file://src/services/question_generator.py#L14-L332)
- [llm_service.py:32-481](file://src/services/llm_service.py#L32-L481)
- [session_state.py:24-139](file://src/models/session_state.py#L24-L139)
- [emotion_type.py:4-50](file://src/enums/emotion_type.py#L4-L50)
- [phase_type.py:4-10](file://src/enums/phase_type.py#L4-L10)
- [memory_query_result.py:23-81](file://src/models/memory_query_result.py#L23-L81)
- [interview_agent.py:16-346](file://src/agents/interview_agent.py#L16-L346)
- [interview_session_agent.py:280-479](file://src/agents/interview_session_agent.py#L280-L479)

**Section sources**
- [question_generator.py:14-332](file://src/services/question_generator.py#L14-L332)
- [llm_service.py:32-481](file://src/services/llm_service.py#L32-L481)
- [session_state.py:24-139](file://src/models/session_state.py#L24-L139)
- [emotion_type.py:4-50](file://src/enums/emotion_type.py#L4-L50)
- [phase_type.py:4-10](file://src/enums/phase_type.py#L4-L10)
- [memory_query_result.py:23-81](file://src/models/memory_query_result.py#L23-L81)
- [interview_agent.py:16-346](file://src/agents/interview_agent.py#L16-L346)
- [interview_session_agent.py:280-479](file://src/agents/interview_session_agent.py#L280-L479)

## Performance Considerations
- Prompt templating overhead: Loading and rendering templates adds latency; reuse formatted variables and minimize repeated template loads.
- Memory context size: Limit the number of entries passed to the LLM to keep prompts concise and reduce token usage.
- Conversation history length: Truncate or summarize recent turns to maintain relevance without bloating the context window.
- Retry and error handling: LLMService includes retry logic; ensure QuestionGenerator falls back gracefully when LLM calls fail.
- **Updated** Candidate question validation: Efficient ID checking and validation to prevent unnecessary processing of invalid candidate selections.
- **Updated** QuestionResult serialization: Minimal overhead for structured output representation compared to raw string processing.

## Troubleshooting Guide
Common issues and resolutions:
- No relevant memory context: QuestionGenerator falls back to default questions per phase; verify KnowledgeBaseQuerier is configured correctly and KnowledgeQueryTool targets the right user directory.
- Emotion detection failures: Emotion-aware fallbacks provide neutral responses; ensure EmotionType values align with the detected emotion and that the emotion response template is loaded.
- Excessive token usage: Reduce memory context length and conversation history size; adjust LLMService temperature and max tokens for balanced creativity and efficiency.
- Phase transition not triggered: Verify coverage thresholds and PhaseType ordering; ensure SessionState.update_coverage is called appropriately.
- **Updated** Invalid candidate questions: QuestionResult validation ensures only valid candidate question IDs are accepted; check candidate question format and ID uniqueness.
- **Updated** JSON parsing errors: Enhanced error handling with fallback to default questions when JSON responses are malformed; review prompt formatting and LLM response consistency.
- **Updated** Source tracking issues: QuestionResult.source field provides clear indication of question origin; verify candidate question selection logic and source validation.

**Section sources**
- [question_generator.py:99-108](file://src/services/question_generator.py#L99-L108)
- [question_generator.py:196-205](file://src/services/question_generator.py#L196-L205)
- [question_generator.py:318-325](file://src/services/question_generator.py#L318-L325)
- [llm_service.py:400-437](file://src/services/llm_service.py#L400-L437)
- [session_state.py:93-96](file://src/models/session_state.py#L93-L96)

## Conclusion
The QuestionGenerator service is the adaptive brain behind the interview experience. By combining emotion-aware responses, progressive disclosure, chronological targeting, and robust integration with InterviewAgent and KnowledgeBaseQuerier, it ensures that each question feels natural, relevant, and sensitive to the user's emotional state. 

**Updated** The new QuestionResult-based architecture enhances traceability, enables sophisticated candidate question management, and provides structured outputs that improve the overall interview experience. The integration with InterviewSessionAgent and enhanced source tracking capabilities make the system more robust and adaptable for complex interview scenarios. The structured prompt system and SessionState-driven decision logic enable consistent, high-quality questioning that balances guided interviewing with organic conversation flow while maintaining detailed provenance of question origins.