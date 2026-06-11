"""Small observability facade for LangChain/Langfuse tracing.

Business code should describe the current operation and node. This module
turns that into stable LangChain config fields consumed by Langfuse.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any, Iterator, Optional
from uuid import uuid4

from langfuse import get_client, propagate_attributes


_CURRENT_CONTEXT: ContextVar[Optional["ObservabilityContext"]] = ContextVar(
    "observability_context",
    default=None,
)


@dataclass(frozen=True)
class ObservabilityContext:
    """Request-level tracing context.

    A context is usually created at an API/runner boundary. Lower layers can
    then derive run names and metadata without carrying user/session values
    through every method signature.
    """

    agent: str
    operation: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    phase: Optional[str] = None
    trace_id: Optional[str] = None
    parent_observation_id: Optional[str] = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.trace_id is None:
            object.__setattr__(self, "trace_id", uuid4().hex)

    def child(self, *, phase: Optional[str] = None, operation: Optional[str] = None) -> "ObservabilityContext":
        return ObservabilityContext(
            agent=self.agent,
            operation=operation or self.operation,
            user_id=self.user_id,
            session_id=self.session_id,
            phase=phase if phase is not None else self.phase,
            trace_id=self.trace_id,
            parent_observation_id=self.parent_observation_id,
            tags=self.tags,
            metadata=dict(self.metadata),
        )

    def llm_config(
        self,
        *,
        node: Optional[str] = None,
        run_name: Optional[str] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        template_name: Optional[str] = None,
        output_model: Optional[str] = None,
    ) -> dict[str, Any]:
        normalized_node = _normalize_node(node)
        name = run_name or self._run_name(normalized_node)

        merged_tags = list(self.tags)
        for item in [self.agent, self.operation, self.phase]:
            if item:
                merged_tags.append(item)
        if normalized_node:
            merged_tags.extend(part for part in normalized_node.split(".") if part)
        if template_name:
            merged_tags.append(template_name)
        if tags:
            merged_tags.extend(tags)

        final_tags = _dedupe([tag for tag in merged_tags if tag])
        merged_metadata = {
            "agent": self.agent,
            "operation": self.operation,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "phase": self.phase,
            "node": normalized_node,
            "trace_id": self.trace_id,
            "template_name": template_name,
            "output_model": output_model,
            "langfuse_user_id": self.user_id,
            "langfuse_session_id": self.session_id,
            "langfuse_trace_name": self.trace_name,
            "langfuse_tags": final_tags,
            **self.metadata,
            **(metadata or {}),
        }

        return {
            "run_name": name,
            "tags": final_tags,
            "metadata": {k: v for k, v in merged_metadata.items() if v is not None},
        }

    @property
    def trace_name(self) -> str:
        return f"{self.agent}.{self.operation}"

    def trace_context(self, *, include_parent: bool = True) -> dict[str, str]:
        context = {"trace_id": self.trace_id or uuid4().hex}
        if include_parent and self.parent_observation_id:
            context["parent_span_id"] = self.parent_observation_id
        return context

    def root_metadata(self) -> dict[str, Any]:
        data = {
            "agent": self.agent,
            "operation": self.operation,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "phase": self.phase,
            "trace_id": self.trace_id,
            **self.metadata,
        }
        return {k: v for k, v in data.items() if v is not None}

    def _run_name(self, node: Optional[str]) -> str:
        if node:
            return f"{self.agent}.{node}"
        return f"{self.agent}.{self.operation}"


@contextmanager
def observability_context(context: ObservabilityContext) -> Iterator[ObservabilityContext]:
    client = get_client()
    root_tags = _dedupe([self_tag for self_tag in [
        *context.tags,
        context.agent,
        context.operation,
        context.phase,
    ] if self_tag])
    with propagate_attributes(
        user_id=context.user_id,
        session_id=context.session_id,
        tags=root_tags,
        metadata=context.root_metadata(),
        trace_name=context.trace_name,
    ):
        with client.start_as_current_observation(
            trace_context=context.trace_context(
                include_parent=context.parent_observation_id is not None,
            ),
            name=context.trace_name,
            as_type="span",
            metadata=context.root_metadata(),
        ):
            active_context = replace(
                context,
                parent_observation_id=client.get_current_observation_id(),
            )
            token = _CURRENT_CONTEXT.set(active_context)
            try:
                yield active_context
            finally:
                _CURRENT_CONTEXT.reset(token)


def get_observability_context() -> Optional[ObservabilityContext]:
    return _CURRENT_CONTEXT.get()


@dataclass
class ApiObservation:
    """Manual route-level observation that can outlive the route function.

    SSE route handlers return an EventSourceResponse before the stream is fully
    consumed, so this object is ended by the async generator after the last event
    has been yielded.
    """

    agent: str
    operation: str
    route: str
    user_id: Optional[str]
    span: Any
    started_perf: float
    session_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    ended: bool = False

    @property
    def trace_id(self) -> str:
        return self.span.trace_id

    @property
    def observation_id(self) -> str:
        return self.span.id

    def set_session_id(self, session_id: str) -> None:
        self.session_id = session_id
        self.metadata["session_id"] = session_id
        self.span.update(metadata=self._metadata("running"))

    def child_context(self, *, operation: Optional[str] = None, phase: Optional[str] = None) -> ObservabilityContext:
        return ObservabilityContext(
            agent=self.agent,
            operation=operation or self.operation,
            user_id=self.user_id,
            session_id=self.session_id,
            phase=phase,
            trace_id=self.trace_id,
            parent_observation_id=self.observation_id,
            metadata={
                "api_route": self.route,
                "api_operation": self.operation,
            },
        )

    def end(self, *, status: str = "completed", output: Optional[Any] = None, error: Optional[BaseException] = None) -> None:
        if self.ended:
            return

        self.ended = True
        elapsed_ms = round((perf_counter() - self.started_perf) * 1000, 3)
        level = "ERROR" if error is not None or status == "failed" else None
        status_message = str(error) if error is not None else None
        final_output = output or {"status": status, "elapsed_ms": elapsed_ms}
        self.span.update(
            output=final_output,
            metadata=self._metadata(status, elapsed_ms=elapsed_ms),
            level=level,
            status_message=status_message,
        )
        self.span.end()

    def _metadata(self, status: str, *, elapsed_ms: Optional[float] = None) -> dict[str, Any]:
        data = {
            "agent": self.agent,
            "operation": self.operation,
            "route": self.route,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "api_status": status,
            **self.metadata,
        }
        if elapsed_ms is not None:
            data["api_elapsed_ms"] = elapsed_ms
        return {k: v for k, v in data.items() if v is not None}


def start_api_observation(
    *,
    agent: str,
    operation: str,
    route: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    input: Optional[Any] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> ApiObservation:
    """Start a route-level observation for end-to-end API timing."""

    client = get_client()
    initial_metadata = {
        "agent": agent,
        "operation": operation,
        "route": route,
        "user_id": user_id,
        "session_id": session_id,
        **(metadata or {}),
    }
    with propagate_attributes(
        user_id=user_id,
        session_id=session_id,
        tags=_dedupe([agent, operation]),
        metadata={k: v for k, v in initial_metadata.items() if v is not None},
        trace_name=f"{agent}.{operation}",
    ):
        span = client.start_observation(
            trace_context={"trace_id": uuid4().hex},
            name=f"api.{agent}.{operation}",
            as_type="span",
            input=input,
            metadata={k: v for k, v in initial_metadata.items() if v is not None},
        )
    return ApiObservation(
        agent=agent,
        operation=operation,
        route=route,
        user_id=user_id,
        span=span,
        started_perf=perf_counter(),
        session_id=session_id,
        metadata=dict(metadata or {}),
    )


@contextmanager
def observe_step(
    node: str,
    *,
    as_type: str = "span",
    input: Optional[Any] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Iterator[Any]:
    """Create a non-LLM Langfuse observation inside the current request trace."""

    context = get_observability_context()
    if context is None:
        yield None
        return

    client = get_client()
    normalized_node = _normalize_node(node) or node
    step_metadata = {
        **context.root_metadata(),
        "node": normalized_node,
        **(metadata or {}),
    }
    with client.start_as_current_observation(
        trace_context=context.trace_context(),
        name=context._run_name(normalized_node),
        as_type=as_type,
        input=input,
        metadata={k: v for k, v in step_metadata.items() if v is not None},
    ) as observation:
        active_context = replace(
            context,
            parent_observation_id=client.get_current_observation_id(),
        )
        token = _CURRENT_CONTEXT.set(active_context)
        try:
            yield observation
        finally:
            _CURRENT_CONTEXT.reset(token)


def build_llm_config(
    *,
    callbacks: Optional[list[Any]] = None,
    existing_config: Optional[dict[str, Any]] = None,
    trace_node: Optional[str] = None,
    trace_run_name: Optional[str] = None,
    trace_tags: Optional[list[str]] = None,
    trace_metadata: Optional[dict[str, Any]] = None,
    template_name: Optional[str] = None,
    output_model: Optional[str] = None,
) -> dict[str, Any]:
    """Build a LangChain config dict with tracing fields merged in."""

    config = dict(existing_config or {})

    if callbacks:
        config["callbacks"] = [*config.get("callbacks", []), *callbacks]

    context = get_observability_context()
    if context is not None:
        trace_config = context.llm_config(
            node=trace_node,
            run_name=trace_run_name,
            tags=trace_tags,
            metadata=trace_metadata,
            template_name=template_name,
            output_model=output_model,
        )
    elif trace_node or trace_run_name or trace_tags or trace_metadata or template_name or output_model:
        node = _normalize_node(trace_node) or template_name
        trace_config = {
            "run_name": trace_run_name or node,
            "tags": _dedupe([*(node or "").split("."), *(trace_tags or [])]),
            "metadata": {
                "node": node,
                "template_name": template_name,
                "output_model": output_model,
                **(trace_metadata or {}),
            },
        }
        trace_config["metadata"] = {
            k: v for k, v in trace_config["metadata"].items() if v is not None
        }
    else:
        trace_config = {}

    if trace_config.get("run_name") and not config.get("run_name"):
        config["run_name"] = trace_config["run_name"]

    config["tags"] = _dedupe([*config.get("tags", []), *trace_config.get("tags", [])])
    config["metadata"] = {
        **config.get("metadata", {}),
        **trace_config.get("metadata", {}),
    }

    return {k: v for k, v in config.items() if v not in (None, [], {})}


def _normalize_node(node: Optional[str]) -> Optional[str]:
    if not node:
        return None
    return node.strip().strip(".").replace(" ", "_")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result
