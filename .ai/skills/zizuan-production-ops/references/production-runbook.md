# Zizuan Production Runbook

## Environment map

| Item | Value |
| --- | --- |
| SSH alias | `zizhuan` |
| Production host | `121.41.33.91` |
| Login account | `root` |
| Repository | `/root/zizhuan` |
| Normal branch | `develop` |
| Git remote | `git@github-zizuan:WangYiKai1017/zizuan.git` |
| API | `http://127.0.0.1:8000` |
| OpenAPI health check | `/openapi.json` |
| API prefix | `/api` |
| Main log | `/tmp/zizuan.log` |
| Production data | `/root/zizhuan/knowledge_base/{user_id}` |
| Debug frontend | `debug_frontend.html`, historically exposed on `8010` with basic authentication; discover current state before relying on it |
| macmini alias | `zizhuan`, configured for the same host and `root` account |

The server has an old Git version. Prefer broadly compatible commands such as `git symbolic-ref --short HEAD`, `git config --get remote.origin.url`, and `git stash save -u NAME`.

## Baseline inspection

Run a compact snapshot before any mutation:

```bash
ssh zizhuan
cd /root/zizhuan
pwd
git symbolic-ref --short HEAD
git rev-parse --short HEAD
git config --get remote.origin.url
git status --short
git stash list
ps -eo pid,ppid,lstart,args | grep '[p]ython3.12 run_server.py'
ss -ltnp | grep -E ':(8000|8010)\b' || true
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/openapi.json
tail -n 100 /tmp/zizuan.log
```

Expected healthy API signals:

- A `python3.12 run_server.py` parent process may have a reloader/server child.
- Port `8000` is listening.
- `/openapi.json` returns `200`.
- Logs include `Application startup complete` and no repeating traceback.

Do not hard-code PIDs. Discover them each time.

## Safe deployment

1. Inspect branch, HEAD, remote, worktree, running command, and health.
2. If the worktree is dirty, review the paths and preserve everything:

```bash
git stash save -u "pre-deploy-stash-$(date +%Y%m%d_%H%M%S)"
git stash list | head
```

3. Update the requested branch without rewriting history:

```bash
git fetch origin develop
git checkout develop
git pull --ff-only origin develop
git rev-parse --short HEAD
git status --short
```

If SSH Git access fails, diagnose the configured alias/key. Do not permanently switch the production remote to HTTPS unless the user explicitly requests it.

4. Run focused checks with production Python 3.12. Select files changed by the deployment rather than compiling the whole data tree:

```bash
python3.12 -m py_compile run_server.py src/service/app.py
```

5. Restart using the established launch form. First discover and stop only the matching service process; confirm port `8000` is released. Then start:

```bash
cd /root/zizhuan
PATH=/usr/local/python3.12/bin:$PATH nohup python3.12 run_server.py > /tmp/zizuan.log 2>&1 &
```

6. Wait briefly while tailing startup output, then verify process, port, and HTTP health. Do not leave a required shell session running when handing control back.

7. Never automatically pop or drop a pre-deployment stash. Report its name so a human can decide whether it is obsolete.

## Process stop and recovery

Find exact service PIDs first:

```bash
pgrep -af '^python3.12 run_server.py$'
```

Send `TERM`, wait and recheck. Account for a reloader child and confirm with `ss` that `8000` is free. Escalate to `KILL` only if graceful shutdown fails and report that escalation.

After an instance reboot, also verify disk space, repository presence, `.env` presence without printing it, data directory presence, DNS/network dependencies, and system time before starting the process.

## API smoke tests

Use `/openapi.json` for non-mutating health:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/openapi.json
```

Inspect OpenAPI before constructing a business request because paths and payloads can change:

```bash
curl -sS http://127.0.0.1:8000/openapi.json
```

The interview start endpoint is `/api/interview/start`, not `/interview/start`, and returns SSE. For a real smoke test, inspect the stream until `done` or `failed`, correlate its session ID in `/tmp/zizuan.log`, and ensure no traceback occurred. A start request creates in-memory user state, so use a test identity or clean it up as part of the test plan.

## Logs and incident triage

Primary application log:

```bash
tail -n 200 /tmp/zizuan.log
tail -f /tmp/zizuan.log
```

Search narrowly by trace ID, user ID, session ID, endpoint, exception, or a bounded time window. Preserve the following incident context:

- User report and expected behavior
- Absolute timestamp and timezone
- User/session/trace identifiers
- Endpoint and HTTP/SSE outcome
- Deployed commit and process start time
- Relevant exception or slow span
- Knowledge-base files read or written
- Root cause, contributing factors, and recommended code/ops changes

Do not paste unrelated user conversations, credentials, or complete environment files into reports.

## Production Langfuse

Production keys live in the server `.env`; local keys may target a different project. Load production variables in the remote shell without echoing them, then use Langfuse's API or the project's tracing client for a targeted trace ID.

Known operational constraints:

- Python HTTPS on the server may fail CA verification while `curl` succeeds. Prefer `curl` for read-only production trace retrieval unless the CA chain is deliberately repaired.
- Trace-level usage may be empty while token usage exists on observations.
- Observation endpoints can return `429` or respond slowly. Query one trace, use narrow pagination, and retry politely.
- Correlate nested observations by trace ID and timestamps. Identify model generations, tool calls, status/error fields, latency, and token usage.

Never reveal `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, model API keys, authorization headers, or complete request payloads containing private user data.

## Knowledge-base operations

`knowledge_base/` is runtime production data and is ignored by Git. A code pull must not remove or replace it.

Inspect one user safely:

```bash
cd /root/zizhuan
find "knowledge_base/USER_ID" -type f -maxdepth 5 -print
du -sh "knowledge_base/USER_ID"
```

Download one user directory to the local repository with replacement semantics only when explicitly requested. A robust pattern is to transfer into a temporary local directory, verify it, move the previous local directory to a backup, then rename the temporary directory into place. For a simple operator command, `rsync -a --delete zizhuan:/root/zizhuan/knowledge_base/USER_ID/ knowledge_base/USER_ID/` mirrors remote content and deletes local-only files, so state that consequence clearly.

Before upload or overwrite, back up the destination directory with a timestamp and compare file counts and total size afterward. Avoid following symlinks outside the selected user directory.

## SSH access management

Install a source machine's public key only:

1. On the source machine, locate `~/.ssh/id_ed25519.pub` or `~/.ssh/id_rsa.pub`. Generate a dedicated key pair there only if none exists.
2. On `zizhuan`, ensure `~/.ssh` is mode `700` and `authorized_keys` is mode `600`.
3. Append the exact public-key line only if absent with `grep -qxF`.
4. Test from the source using `BatchMode=yes` and a connection timeout.
5. Add this host block to the source's SSH config when the shared alias is desired:

```sshconfig
Host zizhuan
  HostName 121.41.33.91
  User root
  IdentityFile ~/.ssh/id_rsa
```

Use the actual private-key filename present on that source machine. Back up its existing SSH config before editing and preserve any required `Include` directive at the top.

## Debug frontend on port 8010

Treat the debug frontend as a separate public attack surface. First discover whether `8010` is listening and which process owns it. If enabling it, require authentication, bind only as broadly as necessary, use credentials supplied through an ignored environment/config file, and avoid putting passwords in process arguments, Git, or shell output. Verify unauthenticated access is rejected and authenticated access serves the intended `debug_frontend.html`. Recheck firewall or cloud security-group exposure and stop the listener when it is no longer needed.
