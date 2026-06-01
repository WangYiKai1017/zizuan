# Deployment and Operations

<cite>
**Referenced Files in This Document**
- [setup.sh](file://setup.sh)
- [setup_env.py](file://setup_env.py)
- [start_service.py](file://start_service.py)
- [start_service.sh](file://start_service.sh)
- [run_server.py](file://run_server.py)
- [requirements.txt](file://requirements.txt)
- [requirements-dev.txt](file://requirements-dev.txt)
- [pyproject.toml](file://pyproject.toml)
- [src/config/llm_config.py](file://src/config/llm_config.py)
- [src/services/llm_service.py](file://src/services/llm_service.py)
- [src/storage/memory_repository.py](file://src/storage/memory_repository.py)
- [src/core/conversation_orchestrator.py](file://src/core/conversation_orchestrator.py)
- [src/agents/interview_agent.py](file://src/agents/interview_agent.py)
- [src/agents/interview_session_agent.py](file://src/agents/interview_session_agent.py)
- [src/prompts/base.py](file://src/prompts/base.py)
- [src/prompts/QuestionGenerator-Prompt.md](file://src/prompts/QuestionGenerator-Prompt.md)
- [src/prompts/EmotionDetector-Prompt.md](file://src/prompts/EmotionDetector-Prompt.md)
- [src/service/app.py](file://src/service/app.py)
</cite>

## Update Summary
**Changes Made**
- Added comprehensive deployment infrastructure documentation covering cross-platform setup scripts
- Documented cloud-ready deployment pipeline with automated dependency management
- Added service startup utilities and launch procedures
- Enhanced environment setup with multiple deployment options
- Updated monitoring and logging configuration for production deployments

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Monitoring and Logging](#monitoring-and-logging)
9. [Environment Setup and Configuration Management](#environment-setup-and-configuration-management)
10. [Deployment Topologies](#deployment-topologies)
11. [Infrastructure Requirements and Scalability](#infrastructure-requirements-and-scalability)
12. [Backup and Recovery Procedures](#backup-and-recovery-procedures)
13. [Security Considerations](#security-considerations)
14. [Maintenance and Operational Procedures](#maintenance-and-operational-procedures)
15. [Troubleshooting Guide](#troubleshooting-guide)
16. [Conclusion](#conclusion)

## Introduction
This document provides comprehensive deployment and operations guidance for the Elderly Memoir Agent system. It covers environment setup, dependency management, configuration, deployment topologies for development, staging, and production, monitoring and logging, performance and error tracking, infrastructure and scalability, backup and recovery, security, maintenance schedules, and troubleshooting. The system now includes comprehensive deployment infrastructure with cross-platform setup scripts, cloud-ready deployment pipeline, and service startup utilities for streamlined operations across different environments.

## Project Structure
The system is organized around a modular Python package with clear separation of concerns:
- Configuration and environment variables for LLM providers
- Services for LLM invocation, emotion detection, knowledge base querying, summarization, and memory management
- Agents for interview orchestration and session lifecycle management
- Core orchestration coordinating agents and services
- Prompt templates and base prompt utilities
- Storage and caching for memory and knowledge base persistence
- **New**: Deployment infrastructure with cross-platform setup scripts and service launch utilities

```mermaid
graph TB
subgraph "Deployment Infrastructure"
SetupBash["setup.sh<br/>Cross-platform setup"]
SetupPy["setup_env.py<br/>Python setup"]
StartPy["start_service.py<br/>Service launcher"]
StartSh["start_service.sh<br/>Shell launcher"]
RunServer["run_server.py<br/>Entry point"]
end
subgraph "Configuration"
LLMCfg["LLMConfig<br/>src/config/llm_config.py"]
end
subgraph "Services"
LLMSvc["LLMService<br/>src/services/llm_service.py"]
KBQ["KnowledgeBaseQuerier<br/>(referenced)"]
Summ["ContentSummarizer<br/>(referenced)"]
Emo["EmotionDetector<br/>(referenced)"]
QGen["QuestionGenerator<br/>(referenced)"]
end
subgraph "Agents"
ISess["InterviewSessionAgent<br/>src/agents/interview_session_agent.py"]
IAgent["InterviewAgent<br/>src/agents/interview_agent.py"]
end
subgraph "Core"
CO["ConversationOrchestrator<br/>src/core/conversation_orchestrator.py"]
end
subgraph "Storage"
MR["MemoryRepository<br/>src/storage/memory_repository.py"]
end
subgraph "Prompts"
PT["PromptTemplate<br/>src/prompts/base.py"]
QGP["QuestionGenerator-Prompt.md"]
EDP["EmotionDetector-Prompt.md"]
end
SetupBash --> SetupPy
SetupPy --> StartPy
StartPy --> RunServer
RunServer --> LLMCfg
LLMCfg --> LLMSvc
LLMSvc --> QGen
LLMSvc --> Emo
LLMSvc --> Summ
LLMSvc --> PT
KBQ --> MR
ISess --> IAgent
ISess --> MR
CO --> ISess
CO --> LLMSvc
CO --> MR
QGen --> PT
Emo --> PT
```

**Diagram sources**
- [setup.sh:1-235](file://setup.sh#L1-L235)
- [setup_env.py:1-290](file://setup_env.py#L1-L290)
- [start_service.py:1-191](file://start_service.py#L1-L191)
- [start_service.sh:1-169](file://start_service.sh#L1-L169)
- [run_server.py:1-23](file://run_server.py#L1-L23)
- [src/config/llm_config.py:10-120](file://src/config/llm_config.py#L10-L120)
- [src/services/llm_service.py:32-125](file://src/services/llm_service.py#L32-L125)
- [src/agents/interview_session_agent.py:33-110](file://src/agents/interview_session_agent.py#L33-L110)
- [src/agents/interview_agent.py:16-80](file://src/agents/interview_agent.py#L16-L80)
- [src/core/conversation_orchestrator.py:138-197](file://src/core/conversation_orchestrator.py#L138-L197)
- [src/storage/memory_repository.py:40-88](file://src/storage/memory_repository.py#L40-L88)
- [src/prompts/base.py:6-33](file://src/prompts/base.py#L6-L33)
- [src/prompts/QuestionGenerator-Prompt.md:1-352](file://src/prompts/QuestionGenerator-Prompt.md#L1-L352)
- [src/prompts/EmotionDetector-Prompt.md:1-259](file://src/prompts/EmotionDetector-Prompt.md#L1-L259)

**Section sources**
- [setup.sh:1-235](file://setup.sh#L1-L235)
- [setup_env.py:1-290](file://setup_env.py#L1-L290)
- [start_service.py:1-191](file://start_service.py#L1-L191)
- [start_service.sh:1-169](file://start_service.sh#L1-L169)
- [run_server.py:1-23](file://run_server.py#L1-L23)
- [requirements.txt:1-22](file://requirements.txt#L1-L22)
- [requirements-dev.txt:1-14](file://requirements-dev.txt#L1-L14)
- [pyproject.toml:1-26](file://pyproject.toml#L1-L26)

## Core Components
- LLM configuration and provider selection via environment variables
- Unified LLM service with retry/backoff, token usage tracking, and structured output support
- Memory repository with short-term, long-term, and profile memory, plus LRU cache
- Interview session and interview agents implementing time-bounded sessions with knowledge base integration
- Conversation orchestrator managing session lifecycle, timing, and state transitions
- Prompt templates and dynamic rendering for emotion detection and question generation
- **New**: Cross-platform deployment infrastructure with automated setup and service management

Key operational implications:
- Environment-driven provider selection enables multi-cloud/provider flexibility
- Structured outputs improve reliability and observability
- Time-bound sessions and warnings ensure predictable user experience
- Knowledge base queries and caching reduce latency and LLM cost
- **New**: Automated deployment pipeline with idempotent setup scripts for consistent environments
- **New**: Multiple launch options for different deployment scenarios (development, staging, production)

**Section sources**
- [src/config/llm_config.py:10-120](file://src/config/llm_config.py#L10-L120)
- [src/services/llm_service.py:32-125](file://src/services/llm_service.py#L32-L125)
- [src/storage/memory_repository.py:40-88](file://src/storage/memory_repository.py#L40-L88)
- [src/agents/interview_session_agent.py:33-110](file://src/agents/interview_session_agent.py#L33-L110)
- [src/agents/interview_agent.py:16-80](file://src/agents/interview_agent.py#L16-L80)
- [src/core/conversation_orchestrator.py:138-197](file://src/core/conversation_orchestrator.py#L138-L197)
- [src/prompts/base.py:6-33](file://src/prompts/base.py#L6-L33)
- [setup.sh:1-235](file://setup.sh#L1-L235)
- [setup_env.py:1-290](file://setup_env.py#L1-L290)
- [start_service.py:1-191](file://start_service.py#L1-L191)
- [start_service.sh:1-169](file://start_service.sh#L1-L169)

## Architecture Overview
The system follows a layered architecture with enhanced deployment infrastructure:
- Presentation/Control Layer: InterviewSessionAgent and InterviewAgent
- Orchestration Layer: ConversationOrchestrator
- Service Layer: LLMService, EmotionDetector, KnowledgeBaseQuerier, QuestionGenerator, ContentSummarizer
- Persistence Layer: MemoryRepository backed by MarkdownFileManager and filesystem storage
- Prompt Layer: Dynamic prompt templates loaded from Markdown and Python modules
- **New**: Deployment Layer: Cross-platform setup scripts and service launch utilities

```mermaid
sequenceDiagram
participant Dev as "Developer"
participant Setup as "Setup Scripts"
participant Env as "Environment"
participant Service as "Service Launcher"
participant App as "FastAPI App"
Dev->>Setup : run setup.sh/setup_env.py
Setup->>Env : create venv, install deps
Env-->>Setup : validated environment
Setup->>Service : launch service
Service->>App : uvicorn run
App-->>Dev : API endpoints available
```

**Diagram sources**
- [setup.sh:1-235](file://setup.sh#L1-L235)
- [setup_env.py:1-290](file://setup_env.py#L1-L290)
- [start_service.py:1-191](file://start_service.py#L1-L191)
- [start_service.sh:1-169](file://start_service.sh#L1-L169)
- [run_server.py:1-23](file://run_server.py#L1-L23)
- [src/service/app.py:22-59](file://src/service/app.py#L22-L59)

## Detailed Component Analysis

### Deployment Infrastructure and Setup Scripts
**New**: The system now includes comprehensive deployment infrastructure with cross-platform support:

#### setup.sh - Bash-based Setup Script
- Idempotent one-click setup for cloud deployment
- Automatic Python detection (python3.11, python3.10, python3)
- Virtual environment creation and activation
- Dependency installation from requirements.txt and requirements-dev.txt
- .env file management with .env.example template
- Environment variable validation and warnings
- Smoke import checks for critical dependencies

#### setup_env.py - Cross-platform Python Setup
- Pure Python implementation for Windows/CI compatibility
- Uses only standard library modules
- Platform-aware path handling for Windows and Unix systems
- Same feature set as setup.sh with Python interface
- Graceful handling of missing dependencies

#### start_service.py - Python Service Launcher
- Cross-platform service startup utility
- Environment variable loading with python-dotenv fallback
- Dependency installation automation
- Uvicorn programmatic startup
- Comprehensive API route documentation

#### start_service.sh - Shell Service Launcher
- Traditional shell-based service startup
- Environment variable validation
- Optional dependency installation
- Uvicorn execution with configurable options

#### run_server.py - Application Entry Point
- Simple entry point for direct execution
- Uvicorn standalone server configuration
- Application factory integration

**Section sources**
- [setup.sh:1-235](file://setup.sh#L1-L235)
- [setup_env.py:1-290](file://setup_env.py#L1-L290)
- [start_service.py:1-191](file://start_service.py#L1-L191)
- [start_service.sh:1-169](file://start_service.sh#L1-L169)
- [run_server.py:1-23](file://run_server.py#L1-L23)

### LLM Configuration and Provider Selection
- Supports Qwen and DeepSeek providers via dedicated environment variables
- Falls back to default provider if provider-specific variables are absent
- Centralized configuration loading and defaults

Operational guidance:
- Set provider-specific variables for primary provider
- Keep LLM temperature and token limits aligned with use case
- Configure timeouts and retries per environment

**Section sources**
- [src/config/llm_config.py:42-120](file://src/config/llm_config.py#L42-L120)

### LLM Service and Prompt Templates
- Unified LLM invocation with retry/backoff and token usage metrics
- Structured output parsing with Pydantic models
- Dynamic prompt template loading from Markdown and Python modules
- Global singleton initialization for convenience

Operational guidance:
- Monitor success rate, latency, and token usage via service stats
- Validate prompt template variables before invoking structured outputs
- Use appropriate temperature and max tokens for each task

**Section sources**
- [src/services/llm_service.py:32-125](file://src/services/llm_service.py#L32-L125)
- [src/services/llm_service.py:225-292](file://src/services/llm_service.py#L225-L292)
- [src/services/llm_service.py:327-398](file://src/services/llm_service.py#L327-L398)
- [src/prompts/base.py:6-33](file://src/prompts/base.py#L6-L33)
- [src/prompts/QuestionGenerator-Prompt.md:1-352](file://src/prompts/QuestionGenerator-Prompt.md#L1-L352)
- [src/prompts/EmotionDetector-Prompt.md:1-259](file://src/prompts/EmotionDetector-Prompt.md#L1-L259)

### Memory Repository and Caching
- Short-term memory with bounded history
- Long-term memory persisted as Markdown files under knowledge base
- LRU cache for frequently accessed entities
- Indexing for people and events to accelerate retrieval

Operational guidance:
- Tune cache capacity and short-term history size for workload
- Ensure knowledge base directories exist and are writable
- Monitor disk usage and implement retention policies

**Section sources**
- [src/storage/memory_repository.py:40-88](file://src/storage/memory_repository.py#L40-L88)
- [src/storage/memory_repository.py:174-200](file://src/storage/memory_repository.py#L174-L200)
- [src/storage/memory_repository.py:228-247](file://src/storage/memory_repository.py#L228-L247)

### Interview Session and Interview Agents
- Session phases: init, profile collection, interview, ending, closed
- Time controls: total duration, profile duration, five-minute archive trigger
- Knowledge base checks and resume logic for returning users
- Archive and cache tools integrated during session

Operational guidance:
- Enforce time budgets rigorously; warn near threshold
- Ensure knowledge base paths are correct and accessible
- Use archive tool to checkpoint progress

**Section sources**
- [src/agents/interview_session_agent.py:24-52](file://src/agents/interview_session_agent.py#L24-L52)
- [src/agents/interview_session_agent.py:112-130](file://src/agents/interview_session_agent.py#L112-L130)
- [src/agents/interview_session_agent.py:178-241](file://src/agents/interview_session_agent.py#L178-L241)
- [src/agents/interview_session_agent.py:341-367](file://src/agents/interview_session_agent.py#L341-L367)
- [src/agents/interview_session_agent.py:369-392](file://src/agents/interview_session_agent.py#L369-L392)
- [src/agents/interview_agent.py:274-283](file://src/agents/interview_agent.py#L274-L283)

### Conversation Orchestrator
- Coordinates emotion detection, knowledge base querying, and question generation
- Manages session timing, state transitions, and handoff preparation
- Emits events for monitoring and observability

Operational guidance:
- Configure timeouts for emotion and query tasks
- Monitor session events and timing warnings
- Prepare handoff packages with coverage and collected data

**Section sources**
- [src/core/conversation_orchestrator.py:138-197](file://src/core/conversation_orchestrator.py#L138-L197)
- [src/core/conversation_orchestrator.py:236-344](file://src/core/conversation_orchestrator.py#L236-L344)
- [src/core/conversation_orchestrator.py:570-592](file://src/core/conversation_orchestrator.py#L570-L592)

## Dependency Analysis
External dependencies include LangChain/LangGraph for LLM orchestration, OpenAI-compatible clients, YAML and dotenv for configuration, watchdog for file monitoring, and loguru for logging. Development dependencies include pytest, black, isort, flake8, and mypy.

```mermaid
graph TB
A["requirements.txt"] --> B["LangChain/LangGraph"]
A --> C["OpenAI/Anthropic clients"]
A --> D["aiofiles/httpx"]
A --> E["python-dotenv/pyyaml/rich/loguru"]
A --> F["watchdog"]
G["requirements-dev.txt"] --> H["pytest/black/isort/flake8/mypy"]
I["pyproject.toml"] --> J["Python >= 3.10"]
K["Deployment Scripts"] --> L["Cross-platform compatibility"]
M["Service Launchers"] --> N["Uvicorn ASGI server"]
O["Environment Config"] --> P["dotenv support"]
```

**Diagram sources**
- [requirements.txt:1-22](file://requirements.txt#L1-L22)
- [requirements-dev.txt:1-14](file://requirements-dev.txt#L1-L14)
- [pyproject.toml](file://pyproject.toml#L6)
- [setup.sh:1-235](file://setup.sh#L1-L235)
- [setup_env.py:1-290](file://setup_env.py#L1-L290)
- [start_service.py:1-191](file://start_service.py#L1-L191)
- [start_service.sh:1-169](file://start_service.sh#L1-L169)

**Section sources**
- [requirements.txt:1-22](file://requirements.txt#L1-L22)
- [requirements-dev.txt:1-14](file://requirements-dev.txt#L1-L14)
- [pyproject.toml](file://pyproject.toml#L6)
- [setup.sh:1-235](file://setup.sh#L1-L235)
- [setup_env.py:1-290](file://setup_env.py#L1-L290)
- [start_service.py:1-191](file://start_service.py#L1-L191)
- [start_service.sh:1-169](file://start_service.sh#L1-L169)

## Performance Considerations
- Asynchronous LLM calls with retry/backoff reduce tail latency and improve resilience
- Structured outputs with JSON parsing enable deterministic processing
- Prompt template loading from Markdown reduces cold-start costs after initial load
- Caching and indexing minimize repeated LLM calls and file reads
- Time-bound sessions prevent runaway resource consumption
- **New**: Optimized deployment scripts reduce setup time and improve reliability

Recommendations:
- Monitor LLM latency and token usage; adjust temperature and max tokens accordingly
- Use connection pooling and limit concurrent requests to provider APIs
- Implement circuit breakers for downstream services
- Cache frequently accessed prompts and templates
- **New**: Utilize deployment scripts for consistent environment setup across teams

## Monitoring and Logging
- LLMService logs call outcomes, errors, and token usage
- ConversationOrchestrator emits session lifecycle events
- Logging library supports structured logging; configure sinks externally
- **New**: Deployment scripts provide detailed setup and startup logging

Guidelines:
- Centralize logs to a collector (e.g., syslog, cloud logging)
- Tag logs with session_id and user_id for correlation
- Alert on high error rates, timeouts, and excessive latency
- Track token consumption and cost metrics
- **New**: Monitor deployment script execution and environment validation

**Section sources**
- [src/services/llm_service.py:15-16](file://src/services/llm_service.py#L15-L16)
- [src/services/llm_service.py:285-291](file://src/services/llm_service.py#L285-L291)
- [src/core/conversation_orchestrator.py:227-231](file://src/core/conversation_orchestrator.py#L227-L231)
- [setup.sh:208-212](file://setup.sh#L208-L212)
- [setup_env.py:252-258](file://setup_env.py#L252-L258)

## Environment Setup and Configuration Management
**Updated**: Enhanced with comprehensive deployment infrastructure:

### Prerequisites
- Python version requirement: see project metadata (>=3.10)
- Install runtime dependencies from requirements.txt
- Install developer/test dependencies from requirements-dev.txt
- **New**: Cross-platform setup script support (bash and Python)

### Configuration Management
- LLM provider selection via environment variables
- Load configuration from .env files using python-dotenv
- Configure logging and prompt template paths
- **New**: Automated .env file creation and validation

### Deployment Options

#### Option 1: Bash-based Setup (Linux/macOS)
```bash
# One-click setup with development dependencies
./setup.sh --dev

# Setup without development dependencies
./setup.sh

# Skip virtual environment creation (Docker/CI)
./setup.sh --no-venv
```

#### Option 2: Python-based Setup (Cross-platform)
```bash
# One-click setup with development dependencies
python setup_env.py --dev

# Setup without development dependencies
python setup_env.py

# Skip virtual environment creation (Docker/CI)
python setup_env.py --no-venv
```

#### Option 3: Service Launch
```bash
# Launch with automatic dependency installation
python start_service.py --install

# Launch with auto-reload for development
python start_service.py --reload

# Launch without auto-reload for production testing
python start_service.py --no-reload

# Check-only mode for environment validation
python start_service.py --check-only
```

**Section sources**
- [pyproject.toml](file://pyproject.toml#L6)
- [requirements.txt:1-22](file://requirements.txt#L1-L22)
- [requirements-dev.txt:1-14](file://requirements-dev.txt#L1-L14)
- [src/config/llm_config.py:6-7](file://src/config/llm_config.py#L6-L7)
- [src/services/llm_service.py:126-161](file://src/services/llm_service.py#L126-L161)
- [setup.sh:1-235](file://setup.sh#L1-L235)
- [setup_env.py:1-290](file://setup_env.py#L1-L290)
- [start_service.py:1-191](file://start_service.py#L1-L191)

## Deployment Topologies
**Updated**: Enhanced with cloud-ready deployment pipeline:

### Development Environment
- Local Python environment with local knowledge base storage
- **New**: Automated setup via deployment scripts
- Development server with auto-reload enabled
- Quick iteration with hot-reload capabilities

### Staging Environment
- Containerized service with ephemeral storage and shared knowledge base mount
- **New**: Consistent environment setup across team members
- Automated dependency management
- Health checks for readiness and liveness

### Production Environment
- Containerized service with persistent storage, secrets management, and observability stack
- **New**: Cloud-ready deployment pipeline
- Automated environment validation
- Scalable service architecture with proper monitoring

### Deployment Pipeline Components
```mermaid
flowchart TD
A["Source Code"] --> B["setup.sh/setup_env.py"]
B --> C["Virtual Environment"]
C --> D["Dependency Installation"]
D --> E[".env Configuration"]
E --> F["Service Launch"]
F --> G["Health Check"]
G --> H["Production Ready"]
```

**Diagram sources**
- [setup.sh:1-235](file://setup.sh#L1-L235)
- [setup_env.py:1-290](file://setup_env.py#L1-L290)
- [start_service.py:1-191](file://start_service.py#L1-L191)
- [start_service.sh:1-169](file://start_service.sh#L1-L169)

**Section sources**
- [setup.sh:1-235](file://setup.sh#L1-L235)
- [setup_env.py:1-290](file://setup_env.py#L1-L290)
- [start_service.py:1-191](file://start_service.py#L1-L191)
- [start_service.sh:1-169](file://start_service.sh#L1-L169)

## Infrastructure Requirements and Scalability
Compute:
- CPU: moderate for LLM inference; scale with concurrency
- Memory: proportional to session concurrency and prompt sizes
- Disk: knowledge base growth; implement retention and archival

Networking:
- Outbound HTTPS to provider APIs
- Internal service mesh for inter-pod communication

Scalability:
- Auto-scaling based on queue length or CPU utilization
- Connection pooling to providers
- Caching layer for frequent queries
- **New**: Deployment scripts support containerized and cloud-native deployments

[No sources needed since this section provides general guidance]

## Backup and Recovery Procedures
Backup scope:
- Knowledge base directories (Markdown files)
- Conversation archives and timelines
- Prompt templates and configuration

Backup strategy:
- Periodic snapshots of knowledge base
- Incremental backups for recent conversations
- Version control for prompt templates

Recovery procedure:
- Restore snapshot to a clean knowledge base path
- Reinitialize session agents pointing to restored path
- Validate conversation continuity and memory queries
- **New**: Use deployment scripts for consistent environment restoration

[No sources needed since this section provides general guidance]

## Security Considerations
- Secrets management: store API keys in environment variables or secret managers
- Least privilege: restrict file system permissions for knowledge base directories
- Network egress: whitelist provider endpoints
- Input sanitization: guard against malicious prompts and file paths
- Audit logs: track sensitive operations and configuration changes
- **New**: Deployment scripts validate environment variables and provide security warnings

[No sources needed since this section provides general guidance]

## Maintenance and Operational Procedures
- Regular dependency updates with testing
- Retention and cleanup of old conversations
- Capacity planning for storage and compute
- Patching provider SDKs and Python runtime
- Drills for backup restoration and incident response
- **New**: Automated environment validation and health checks
- **New**: Cross-platform deployment consistency across teams

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- Provider configuration errors: verify environment variables and fallback logic
- LLM timeouts or failures: check retry/backoff and provider quotas
- Missing knowledge base: ensure directories exist and are writable
- Prompt template parsing errors: validate Markdown format and variable completeness
- Session timing anomalies: review timing thresholds and event emissions
- **New**: Setup script failures: check Python version, pip installation, and virtual environment creation
- **New**: Service launch issues: verify environment variables, dependency installation, and port availability

Diagnostic steps:
- Inspect logs for error messages and stack traces
- Verify environment variables and .env loading
- Confirm prompt template registration and variable validation
- Check disk space and file permissions
- **New**: Review deployment script output for setup failures
- **New**: Validate service launcher arguments and configuration

**Section sources**
- [src/config/llm_config.py:42-120](file://src/config/llm_config.py#L42-L120)
- [src/services/llm_service.py:400-437](file://src/services/llm_service.py#L400-L437)
- [src/storage/memory_repository.py:122-161](file://src/storage/memory_repository.py#L122-L161)
- [src/prompts/base.py:29-33](file://src/prompts/base.py#L29-L33)
- [setup.sh:185-203](file://setup.sh#L185-L203)
- [setup_env.py:240-247](file://setup_env.py#L240-L247)
- [start_service.py:108-115](file://start_service.py#L108-L115)
- [start_service.sh:118-132](file://start_service.sh#L118-L132)

## Conclusion
This guide outlines a practical, repeatable approach to deploying and operating the Elderly Memoir Agent system. The addition of comprehensive deployment infrastructure with cross-platform setup scripts, cloud-ready deployment pipeline, and service startup utilities significantly enhances the system's operability and maintainability. By leveraging environment-driven configuration, robust LLM service primitives, structured prompts, disciplined storage and caching, and automated deployment tools, the system achieves reliability, observability, and maintainability across development, staging, and production environments. The deployment scripts ensure consistent environment setup across different platforms and team members, while the service launch utilities provide flexible deployment options for various operational scenarios. Adopt the recommended practices for monitoring, security, backup, and scalability to sustain high-quality user experiences over time.