"""Shared helpers for the standalone integration test scripts.

Kept dependency-light: only the standard library and `requests`.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Generator, Optional, Tuple

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover
    print(
        "[FATAL] The 'requests' package is required. Install with: "
        "pip install requests",
        file=sys.stderr,
    )
    raise


BASE_URL: str = os.getenv("SERVICE_URL", "http://localhost:8000").rstrip("/")

# Default timeouts (seconds)
DEFAULT_TIMEOUT: float = 60.0
SSE_READ_TIMEOUT: float = 300.0  # agent execution can be slow


def section(title: str) -> None:
    """Print a clear section header so progress is easy to follow live."""
    bar = "=" * max(8, 70 - len(title))
    print(f"\n=== {title} {bar}", flush=True)


def info(msg: str) -> None:
    print(f"[INFO] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", flush=True)


def err(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr, flush=True)


def sse_iter(
    response: "requests.Response",
) -> Generator[Tuple[str, Dict[str, Any]], None, None]:
    """Parse an SSE stream from a streaming `requests` Response.

    Yields (event_name, data_dict) tuples as events arrive.

    The server uses sse-starlette which emits standard SSE wire format::

        event: <name>
        data: <json>
        <blank line>

    Each event block is terminated by a blank line. Within a block:
      - ``event: <name>``  — event type (default ``"message"`` if absent)
      - ``data: <text>``   — payload; multiple ``data:`` lines are
        concatenated with ``\n`` per the SSE spec
      - lines starting with ``:`` are comments / heartbeats (ignored)
      - ``id:`` / ``retry:`` are accepted but ignored

    The data payload is parsed as JSON when possible; otherwise it is
    returned as ``{"raw": "<string>"}``.

    Implementation notes:
      * Reads the underlying stream byte-by-byte via ``iter_content`` so
        we never depend on requests' line buffering, which is known to
        merge or split lines unpredictably on chunked SSE responses.
      * Normalizes both LF (``\n``) and CRLF (``\r\n``) line endings, so
        the same parser works regardless of which separator the server
        (or any intermediary proxy) emits.
    """
    # Force utf-8 so iter_content(decode_unicode=True) works correctly
    response.encoding = "utf-8"
    buf = ""

    for chunk in response.iter_content(chunk_size=1, decode_unicode=True):
        if chunk is None or chunk == "":
            continue
        # Normalize CRLF -> LF as we accumulate so the delimiter check
        # works whether the server uses "\n\n" or "\r\n\r\n".
        buf += chunk.replace("\r\n", "\n").replace("\r", "\n")

        # Process all complete event blocks (delimited by blank line)
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            result = _parse_sse_block(block)
            if result is not None:
                yield result

    # Flush remaining buffer (stream closed without trailing blank line)
    if buf.strip():
        result = _parse_sse_block(buf)
        if result is not None:
            yield result


def _parse_sse_block(block: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Parse a single SSE event block into (event_name, data_dict).

    Returns ``None`` if the block contains no meaningful event/data
    (e.g. it's purely whitespace, comments, or heartbeats).
    """
    event_name: Optional[str] = None
    data_lines: list[str] = []

    for raw_line in block.split("\n"):
        # Normalize any stray \r
        line = raw_line.rstrip("\r").lstrip("\r")

        if not line:
            continue

        # Comments / heartbeats per SSE spec
        if line.startswith(":"):
            continue

        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            # Per SSE spec, a single leading space after the colon is
            # part of the field separator and must be stripped.
            value = line[len("data:"):]
            if value.startswith(" "):
                value = value[1:]
            data_lines.append(value)
        elif line.startswith("id:") or line.startswith("retry:"):
            continue
        # Unknown / malformed lines are silently ignored

    if event_name is None and not data_lines:
        return None

    data_str = "\n".join(data_lines)
    if data_str:
        try:
            data_obj = json.loads(data_str)
            if not isinstance(data_obj, dict):
                data_obj = {"raw": data_obj}
        except (json.JSONDecodeError, ValueError):
            data_obj = {"raw": data_str}
    else:
        data_obj = {}

    return (event_name or "message", data_obj)


def print_sse_event(event_name: str, data: Dict[str, Any]) -> None:
    """Pretty-print one SSE event live, truncating overly long values."""
    snippet_parts: list[str] = []
    for k, v in data.items():
        if k == "timestamp":
            continue
        if isinstance(v, str):
            short = v if len(v) <= 200 else v[:200] + "…"
            snippet_parts.append(f"{k}={short!r}")
        else:
            snippet_parts.append(f"{k}={v!r}")
    snippet = ", ".join(snippet_parts) if snippet_parts else "(no fields)"
    print(f"  [SSE] event={event_name} | {snippet}", flush=True)


def summarize(name: str, ok: bool, failures: list[str]) -> int:
    """Print a final PASS/FAIL summary and return an exit code."""
    section(f"SUMMARY: {name}")
    if ok and not failures:
        print(f"[PASS] {name}: all checks passed", flush=True)
        return 0
    print(f"[FAIL] {name}: {len(failures)} check(s) failed", flush=True)
    for f in failures:
        print(f"  - {f}", flush=True)
    return 1


__all__ = [
    "BASE_URL",
    "DEFAULT_TIMEOUT",
    "SSE_READ_TIMEOUT",
    "info",
    "warn",
    "err",
    "section",
    "sse_iter",
    "print_sse_event",
    "summarize",
    "requests",
]
