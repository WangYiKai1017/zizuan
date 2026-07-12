#!/usr/bin/env python3
"""Render Claude Code stream-json logs as readable Chinese text."""

from __future__ import annotations

import json
import sys
from typing import Any


OUTPUT: list[str] = []


def out(text: str = "") -> None:
    OUTPUT.append(text)


def compact(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def fence(text: str) -> str:
    text = text.rstrip()
    if not text:
        return "（空）"
    return f"```text\n{text}\n```"


def render_tool_input(raw_json: str) -> str:
    raw_json = raw_json.strip()
    if not raw_json:
        return "（无参数）"
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return fence(raw_json)

    lines: list[str] = []
    description = data.get("description")
    command = data.get("command")
    if description:
        lines.append(f"说明：{description}")
    if command:
        lines.append("命令：")
        lines.append(fence(command))

    rest = {key: value for key, value in data.items() if key not in {"description", "command"}}
    if rest:
        lines.append("参数：")
        lines.append(fence(json.dumps(rest, ensure_ascii=False, indent=2)))
    return "\n".join(lines) if lines else fence(json.dumps(data, ensure_ascii=False, indent=2))


def render_content_blocks(blocks: list[dict[str, Any]], fallback_title: str) -> None:
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            text = compact(block.get("text")).strip()
            if text:
                out("### 助手输出")
                out(text)
                out()
        elif block_type == "thinking":
            thinking = compact(block.get("thinking")).strip()
            if thinking:
                out("### 思考过程（已组装）")
                out(thinking)
                out()
        elif block_type == "tool_use":
            out(f"### 工具调用：{block.get('name', 'unknown')}")
            tool_input = block.get("input")
            if isinstance(tool_input, dict):
                out(render_tool_input(json.dumps(tool_input, ensure_ascii=False)))
            else:
                out(render_tool_input(compact(tool_input)))
            out()
        elif block_type == "tool_result":
            out(f"### {fallback_title}")
            content = compact(block.get("content")).strip()
            out(fence(content))
            out()
        else:
            out(f"### {fallback_title}：{block_type or 'unknown'}")
            out(fence(json.dumps(block, ensure_ascii=False, indent=2)))
            out()


def main() -> int:
    blocks: dict[int, dict[str, Any]] = {}
    saw_stream_blocks = False

    out("## Claude Code 可读日志")
    out()

    for raw_line in sys.stdin:
        line = raw_line.rstrip("\n")
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            out(line)
            continue

        event_type = event.get("type")

        if event_type == "system" and event.get("subtype") == "init":
            out("### 会话初始化")
            out(f"- 工作目录：{event.get('cwd', '')}")
            out(f"- 会话 ID：{event.get('session_id', '')}")
            out(f"- 模型：{event.get('model', '')}")
            out(f"- 权限模式：{event.get('permissionMode', '')}")
            agents = event.get("agents") or []
            if agents:
                out(f"- 可用 Agent：{', '.join(agents)}")
            out()
            continue

        if event_type == "stream_event":
            stream = event.get("event") or {}
            stream_type = stream.get("type")

            if stream_type == "message_start":
                message = stream.get("message") or {}
                role = message.get("role", "assistant")
                model = message.get("model", "")
                out(f"### {role} 开始响应")
                if model:
                    out(f"- 响应模型：{model}")
                out()
                continue

            if stream_type == "content_block_start":
                saw_stream_blocks = True
                index = int(stream.get("index", 0))
                content_block = dict(stream.get("content_block") or {})
                content_block.setdefault("_buffer", "")
                blocks[index] = content_block
                continue

            if stream_type == "content_block_delta":
                index = int(stream.get("index", 0))
                block = blocks.setdefault(index, {"type": "unknown", "_buffer": ""})
                delta = stream.get("delta") or {}
                delta_type = delta.get("type")
                if delta_type == "text_delta":
                    block["_buffer"] = block.get("_buffer", "") + compact(delta.get("text"))
                    block["text"] = block.get("_buffer", "")
                elif delta_type == "thinking_delta":
                    block["_buffer"] = block.get("_buffer", "") + compact(delta.get("thinking"))
                    block["thinking"] = block.get("_buffer", "")
                elif delta_type == "input_json_delta":
                    block["_buffer"] = block.get("_buffer", "") + compact(delta.get("partial_json"))
                    block["input"] = block.get("_buffer", "")
                else:
                    block["_buffer"] = block.get("_buffer", "") + compact(delta)
                continue

            if stream_type == "content_block_stop":
                index = int(stream.get("index", 0))
                block = blocks.pop(index, None)
                if block:
                    render_content_blocks([block], "内容块")
                continue

            if stream_type == "message_delta":
                delta = stream.get("delta") or {}
                usage = stream.get("usage") or {}
                stop_reason = delta.get("stop_reason")
                if stop_reason or usage:
                    out("### 响应状态")
                    if stop_reason:
                        out(f"- 停止原因：{stop_reason}")
                    if usage:
                        input_tokens = usage.get("input_tokens")
                        output_tokens = usage.get("output_tokens")
                        out(f"- Token：input={input_tokens}, output={output_tokens}")
                    out()
                continue

            out(f"### 流事件：{stream_type or 'unknown'}")
            out(fence(json.dumps(stream, ensure_ascii=False, indent=2)))
            out()
            continue

        if event_type in {"assistant", "user"}:
            # Claude Code repeats full assistant messages after stream deltas.
            # When we already rendered the assembled stream blocks, skip those
            # duplicates but still render non-streamed user/tool result messages.
            if event_type == "assistant" and saw_stream_blocks:
                continue
            message = event.get("message") or {}
            title = "助手消息" if event_type == "assistant" else "工具结果/用户消息"
            render_content_blocks(message.get("content") or [], title)
            continue

        if event_type == "result":
            out("### 执行结果")
            subtype = event.get("subtype")
            if subtype:
                out(f"- 类型：{subtype}")
            if "is_error" in event:
                out(f"- 是否错误：{event.get('is_error')}")
            if "duration_ms" in event:
                out(f"- 耗时：{event.get('duration_ms')} ms")
            if "total_cost_usd" in event:
                out(f"- 费用：${event.get('total_cost_usd')}")
            result = compact(event.get("result")).strip()
            if result:
                out(result)
            out()
            continue

        out(f"### 事件：{event_type or 'unknown'}")
        out(fence(json.dumps(event, ensure_ascii=False, indent=2)))
        out()

    for index in sorted(blocks):
        render_content_blocks([blocks[index]], "未结束内容块")

    print("\n".join(OUTPUT), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
