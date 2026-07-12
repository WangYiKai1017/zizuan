#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOOP_DIR="$ROOT_DIR/scripts/loop"
LOOPCTL="$LOOP_DIR/loopctl.py"
PROMPT_FILE="$LOOP_DIR/loop_cmd.md"
LOG_FILE="$LOOP_DIR/loop.log"
STREAM_PRETTY="$LOOP_DIR/claude_stream_pretty.py"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
IDLE_SLEEP_SECONDS="${IDLE_SLEEP_SECONDS:-300}"
ACTIVE_SLEEP_SECONDS="${ACTIVE_SLEEP_SECONDS:-60}"
LEASE_MINUTES="${LEASE_MINUTES:-1}"

: > "$LOG_FILE"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

require_file() {
  if [[ ! -f "$1" ]]; then
    log "缺少必要文件：$1"
    exit 1
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "缺少必要命令：$1"
    exit 1
  fi
}

has_pending_delegations() {
  local token
  local output
  local rc

  token="$("$PYTHON_BIN" "$LOOPCTL" run-begin --lease-minutes "$LEASE_MINUTES" 2>&1)"
  rc=$?
  printf '%s\n' "$token" | tee -a "$LOG_FILE" >/dev/null
  if [[ $rc -ne 0 ]]; then
    return 1
  fi

  output="$("$PYTHON_BIN" "$LOOPCTL" pipeline-all --run-token "$token" 2>&1)"
  rc=$?
  if [[ -n "$output" ]]; then
    printf '%s\n' "$output" | tee -a "$LOG_FILE" >/dev/null
  fi

  "$PYTHON_BIN" "$LOOPCTL" run-end "$token" 2>&1 | tee -a "$LOG_FILE" >/dev/null

  if [[ $rc -ne 0 ]]; then
    return 1
  fi
  [[ -n "$output" ]]
}

run_loop_once() {
  local prompt
  prompt="$(cat "$PROMPT_FILE")"
  log "启动 Claude Code：$CLAUDE_BIN --print --permission-mode bypassPermissions --verbose --output-format stream-json --include-partial-messages --include-hook-events < $PROMPT_FILE"
  "$CLAUDE_BIN" \
    --print \
    --permission-mode bypassPermissions \
    --verbose \
    --output-format stream-json \
    --include-partial-messages \
    --include-hook-events \
    "$prompt" 2>&1 | "$PYTHON_BIN" "$STREAM_PRETTY" | tee -a "$LOG_FILE"
  return "${PIPESTATUS[0]}"
}

main() {
  cd "$ROOT_DIR" || exit 1
  require_file "$PYTHON_BIN"
  require_file "$LOOPCTL"
  require_file "$PROMPT_FILE"
  require_file "$STREAM_PRETTY"
  require_command "$CLAUDE_BIN"

  log "loop 监控已启动"
  log "项目根目录：$ROOT_DIR"
  log "日志文件：$LOG_FILE"
  log "Prompt 文件：$PROMPT_FILE"
  log "日志解析器：$STREAM_PRETTY"
  log "默认 CLI：$CLAUDE_BIN"

  while true; do
    log "检查是否存在待运行委派"
    if has_pending_delegations; then
      log "发现待运行委派，启动 Claude Code 执行一轮 loop"
      if run_loop_once; then
        log "Claude Code 本轮 loop 执行完成"
      else
        log "Claude Code 本轮 loop 执行失败，退出码：$?"
      fi
      log "本轮有委派，休眠 ${ACTIVE_SLEEP_SECONDS} 秒后继续"
      sleep "$ACTIVE_SLEEP_SECONDS"
    else
      log "没有待运行委派，休眠 ${IDLE_SLEEP_SECONDS} 秒后继续检查"
      sleep "$IDLE_SLEEP_SECONDS"
    fi
  done
}

main "$@"
