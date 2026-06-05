#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_FIELDS = "core,basic,time,io,metadata,model,usage,metrics,trace_context"


def load_dotenv(project_root: Path) -> None:
    env_path = project_root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip().strip('"')
    if not value:
        raise SystemExit(f"缺少环境变量 {name}；请检查项目根目录 .env 或当前 shell 环境。")
    return value


def request_json(base_url: str, public_key: str, secret_key: str, path: str, retries: int = 2) -> dict[str, Any]:
    auth = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")
    url = base_url.rstrip("/") + path
    last_error = ""
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            last_error = f"HTTP {exc.code}: {body}"
            if exc.code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise RuntimeError(last_error) from exc
        except Exception as exc:
            last_error = str(exc)
            if attempt == retries:
                raise RuntimeError(last_error) from exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last_error)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_v2_observations(
    *,
    trace_id: str,
    base_url: str,
    public_key: str,
    secret_key: str,
    days: int,
    limit: int,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    params: dict[str, str] = {
        "traceId": trace_id,
        "fromStartTime": iso_z(now - timedelta(days=days)),
        "toStartTime": iso_z(now + timedelta(minutes=5)),
        "limit": str(limit),
        "fields": DEFAULT_FIELDS,
    }
    rows: list[dict[str, Any]] = []
    cursor = ""
    while True:
        query = dict(params)
        if cursor:
            query["cursor"] = cursor
        path = "/api/public/v2/observations?" + urllib.parse.urlencode(query)
        data = request_json(base_url, public_key, secret_key, path)
        batch = data.get("data") or []
        if not isinstance(batch, list):
            raise RuntimeError("Langfuse v2 observations 返回格式异常：data 不是列表")
        rows.extend(batch)
        meta = data.get("meta") or {}
        cursor = meta.get("cursor") or ""
        if not cursor:
            break
    rows.sort(key=lambda row: (row.get("startTime") or "", row.get("id") or ""))
    return rows


def compact(value: Any, max_chars: int = 900) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    text = " ".join(text.split())
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


def trace_summary(rows: list[dict[str, Any]], trace_id: str) -> dict[str, Any]:
    first = rows[0] if rows else {}
    names = [row.get("name") for row in rows if row.get("name")]
    errors = [
        row for row in rows
        if row.get("level") not in (None, "DEFAULT") or row.get("statusMessage")
    ]
    generations = [row for row in rows if str(row.get("type", "")).upper() == "GENERATION"]
    total_usage = sum(int(row.get("totalUsage") or 0) for row in rows)
    total_cost = sum(float(row.get("totalCost") or 0) for row in rows)
    return {
        "trace_id": trace_id,
        "trace_name": first.get("traceName"),
        "user_id": first.get("userId"),
        "session_id": first.get("sessionId"),
        "tags": first.get("tags") or [],
        "observation_count": len(rows),
        "generation_count": len(generations),
        "error_like_count": len(errors),
        "total_usage": total_usage,
        "total_cost": total_cost,
        "first_start_time": rows[0].get("startTime") if rows else None,
        "last_start_time": rows[-1].get("startTime") if rows else None,
        "observation_names": names,
    }


def write_timeline(rows: list[dict[str, Any]], out_path: Path, summary: dict[str, Any]) -> None:
    lines = [
        f"# Langfuse Trace Timeline: {summary['trace_id']}",
        "",
        f"- trace_name: `{summary.get('trace_name') or ''}`",
        f"- user_id: `{summary.get('user_id') or ''}`",
        f"- session_id: `{summary.get('session_id') or ''}`",
        f"- observation_count: `{summary.get('observation_count')}`",
        f"- generation_count: `{summary.get('generation_count')}`",
        "",
    ]
    for i, row in enumerate(rows, 1):
        lines.extend([
            f"## {i}. {row.get('name') or '(unnamed)'}",
            "",
            f"- id: `{row.get('id')}`",
            f"- type: `{row.get('type')}`",
            f"- start: `{row.get('startTime')}`",
            f"- end: `{row.get('endTime')}`",
            f"- parent: `{row.get('parentObservationId') or ''}`",
            f"- level/status: `{row.get('level') or ''}` / `{row.get('statusMessage') or ''}`",
            f"- model: `{row.get('model') or row.get('providedModelName') or ''}`",
            f"- usage: input `{row.get('inputUsage') or ''}`, output `{row.get('outputUsage') or ''}`, total `{row.get('totalUsage') or ''}`",
            f"- latency: `{row.get('latency') or ''}`",
            "",
        ])
        metadata = row.get("metadata")
        if metadata:
            lines.extend(["**metadata**", "", "```json", json.dumps(metadata, ensure_ascii=False, indent=2, default=str)[:3000], "```", ""])
        if row.get("input") is not None:
            lines.extend(["**input 摘要**", "", compact(row.get("input")), ""])
        if row.get("output") is not None:
            lines.extend(["**output 摘要**", "", compact(row.get("output")), ""])
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def automatic_findings(rows: list[dict[str, Any]], summary: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if not rows:
        findings.append("未拉取到任何 observation。请扩大 --days 时间窗口，或确认 trace_id 与当前 Langfuse project 匹配。")
        return findings
    if not summary.get("user_id"):
        findings.append("trace 缺少 user_id，后续难以关联到业务用户。")
    if not summary.get("session_id"):
        findings.append("trace 缺少 session_id，难以关联一次会话或任务。")
    if summary.get("error_like_count"):
        findings.append(f"发现 {summary['error_like_count']} 个非默认 level 或带 statusMessage 的 observation，需要优先检查。")
    if summary.get("generation_count") == 0:
        findings.append("没有 GENERATION observation；如果这是一次 LLM/Agent 调用，可能没有正确记录模型调用。")
    long_rows = [row for row in rows if row.get("latency") and float(row["latency"]) > 30]
    if long_rows:
        findings.append(f"发现 {len(long_rows)} 个 latency > 30s 的 observation，需检查慢调用、重试或阻塞。")
    empty_outputs = [row for row in rows if str(row.get("type", "")).upper() == "GENERATION" and not row.get("output")]
    if empty_outputs:
        findings.append(f"发现 {len(empty_outputs)} 个 generation 输出为空。")
    def row_phase(row: dict[str, Any]) -> str:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        return str(metadata.get("phase") or row.get("phase") or "").lower()

    def row_node(row: dict[str, Any]) -> str:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        return f"{row.get('name') or ''} {metadata.get('node') or ''} {row.get('traceName') or ''}".lower()

    names = " ".join(str(row.get("name") or "") for row in rows)
    profile_indices = [
        i for i, row in enumerate(rows)
        if row_phase(row) == "profile" or ".profile." in row_node(row)
    ]
    formal_interview_indices = [
        i for i, row in enumerate(rows)
        if row_phase(row) in {"interview", "guided_initial", "guided_interview"}
        or ".guided_initial" in row_node(row)
        or ".guided." in row_node(row)
        or row_node(row).strip() == "interview.start"
    ]
    if profile_indices and formal_interview_indices and min(formal_interview_indices) < min(profile_indices):
        findings.append("正式采访/受控采访节点早于 profile 节点出现，需核对新用户流程是否跳过画像。")
    if "story_generation" in names:
        event_path_mentions = sum(1 for row in rows if "event_paths" in compact(row.get("metadata"), 2000) or "selected_event_paths" in compact(row.get("output"), 2000))
        if event_path_mentions == 0:
            findings.append("story_generation trace 中没有明显的来源事件路径记录，需核对是否满足 15 个 event 的溯源要求。")
    return findings


def write_analysis(rows: list[dict[str, Any]], out_path: Path, summary: dict[str, Any]) -> None:
    findings = automatic_findings(rows, summary)
    lines = [
        f"# Langfuse Trace 分析底稿: {summary['trace_id']}",
        "",
        "## 基本信息",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## 自动发现的风险信号",
        "",
    ]
    if findings:
        lines.extend(f"- {item}" for item in findings)
    else:
        lines.append("- 未发现明显结构性风险；仍需结合业务期望逐项核对。")
    lines.extend([
        "",
        "## 业务期望核对清单",
        "",
        "- 新用户流程：画像字段必须先完成或预填；正式采访 start 后必须能对应同一个 user_id 文件夹。",
        "- 画像预填：微信侧姓名、年龄、出生日期、性别、wechat_id 不应被语音识别覆盖成错误值。",
        "- 初期受控采访：应优先推进静态预设问题；每个预设问题最多追问 1 次；允许自然接住强情绪和相关候选问题。",
        "- 候选问题：如果 AI 使用候选问题，API 响应应保留 candidate_question_id，便于前端标记已消费。",
        "- 故事生成：未消费 event 不足 15 个时应失败；够 15 个时只消费最早 15 个；故事保存成功后再更新 stories/.story_state.json。",
        "- 传记/故事边界：故事生成不应走传记 outline/writing 流程；传记写作不应改写 story 状态。",
        "- 观测完整性：trace 中应能看到 agent、operation、user_id、session_id、node 等 metadata；异常不应只体现在日志而没有 trace 信号。",
        "",
        "## 下一步人工分析要求",
        "",
        "1. 从 `timeline.md` 逐个节点还原实际执行路径。",
        "2. 对照上面的业务期望，指出“事实 -> 偏差 -> 影响 -> 建议修复”。",
        "3. 不要只总结模型回复；重点检查阶段顺序、状态持久化、错误处理、候选问题/事件消费等业务约束。",
    ])
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="拉取单个 Langfuse trace 的 observations 并生成本地分析底稿。")
    parser.add_argument("trace_id", help="Langfuse trace id")
    parser.add_argument("--project-root", default=".", help="项目根目录，默认当前目录")
    parser.add_argument("--out-dir", default="", help="输出目录；默认 .agents/runs/langfuse-traces/<trace_id>")
    parser.add_argument("--days", type=int, default=30, help="向前查询多少天，默认 30")
    parser.add_argument("--limit", type=int, default=100, help="每页 observation 数量，默认 100")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    load_dotenv(project_root)
    base_url = require_env("LANGFUSE_BASE_URL")
    public_key = require_env("LANGFUSE_PUBLIC_KEY")
    secret_key = require_env("LANGFUSE_SECRET_KEY")

    out_dir = Path(args.out_dir) if args.out_dir else project_root / ".agents" / "runs" / "langfuse-traces" / args.trace_id
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = fetch_v2_observations(
        trace_id=args.trace_id,
        base_url=base_url,
        public_key=public_key,
        secret_key=secret_key,
        days=args.days,
        limit=args.limit,
    )
    summary = trace_summary(rows, args.trace_id)
    payload = {
        "fetched_at": iso_z(datetime.now(timezone.utc)),
        "source": {
            "base_url": base_url,
            "api": "/api/public/v2/observations",
            "days": args.days,
            "fields": DEFAULT_FIELDS,
        },
        "summary": summary,
        "observations": rows,
    }
    (out_dir / "raw_observations.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_timeline(rows, out_dir / "timeline.md", summary)
    write_analysis(rows, out_dir / "analysis.md", summary)

    print(json.dumps({
        "trace_id": args.trace_id,
        "observation_count": len(rows),
        "out_dir": str(out_dir),
        "files": ["raw_observations.json", "timeline.md", "analysis.md"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
