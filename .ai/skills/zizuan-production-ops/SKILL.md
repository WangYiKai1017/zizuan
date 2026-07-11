---
name: zizuan-production-ops
description: Operate and troubleshoot the Zizuan production server over SSH, including access setup, health checks, Git deployment, process restart and recovery, log inspection, API smoke tests, knowledge-base transfer, production Langfuse investigation, and the authenticated debug frontend. Use when the user mentions zizhuan/zizuan, the online or production service, deployment, restart, logs, timeout, server recovery, production knowledge-base files, SSH access, port 8000/8010, or production Langfuse.
---

# Zizuan Production Ops

Operate the production host conservatively and verify every state-changing action. Treat the server's current state as authoritative; PIDs, commits, logs, and listeners change over time.

## Load the environment reference

Read [references/production-runbook.md](references/production-runbook.md) before performing production work. It contains host aliases, paths, process layout, deployment steps, smoke tests, data handling, and Langfuse diagnostics.

## Follow the operating loop

1. Restate the requested scope: inspect, diagnose, deploy, restart, transfer data, or modify access.
2. Connect with `ssh zizhuan`. If operating from macmini, use the same alias there.
3. Discover current state before changing anything: repository branch and status, running processes, listeners, health endpoint, and recent logs.
4. Preserve unrelated or unknown changes. Do not delete, reset, checkout, clean, or overwrite them. Stash with untracked files or create a timestamped backup when deployment requires a clean tree.
5. Make only the requested change. Never print or copy secrets into chat, skill files, shell history, Git, or logs.
6. Verify at three levels when applicable: process exists, port/health responds, and the requested API behavior succeeds.
7. Report the deployed commit, service status, smoke-test result, retained backups/stashes, and any residual risk.

## Apply production safety rules

- Prefer read-only inspection until the user authorizes a mutation.
- Treat restart, pull, file overwrite, process termination, key installation, and environment changes as production mutations.
- Never use `git reset --hard`, `git clean`, or destructive checkout for deployment.
- Never replace `knowledge_base/` as part of a code deployment. It is production data, not source code.
- Never inspect `.env` with commands that echo the whole file. Query only variable names or load values directly into a command.
- Keep SSH key operations one-way: install public keys only; never move private keys between machines.
- Use idempotent authorization updates: append a public key only if the exact line is absent.
- Do not assume a successful HTTP status means an SSE workflow completed. Inspect events through `done` or `failed`.
- Avoid creating a live user session merely for health checking. If a real `/start` smoke test is required, use an agreed test user or clean up the in-memory session afterward.
- Production Langfuse requests can be slow or rate-limited. Query a single trace/session and paginate narrowly instead of bulk-fetching observations.

## Handle common requests

### Inspect or recover the service

Check the health endpoint, listener, parent and child Python processes, and recent log tail. If the instance rebooted and no process is listening, start it with the established command from the runbook, then verify startup and HTTP health.

### Deploy code

Confirm the desired branch and remote state. Preserve a dirty worktree, update with a fast-forward pull, run focused Python 3.12 syntax checks, restart with the established command, and smoke test. Record any stash rather than silently applying or dropping it.

### Diagnose an API failure

Correlate the request time, user ID, session ID, endpoint, application logs, and Langfuse trace. Separate transport timeout, server exception, slow model/tool call, and incomplete business output. Do not patch code unless the user also asks for a fix.

### Transfer knowledge-base data

Operate on one explicit `user_id` directory. Show source and destination, check size and free space, preserve or overwrite exactly as requested, and validate file counts after transfer. Keep `knowledge_base/` ignored by Git.

### Modify SSH access

Read the source machine's existing public key or generate a new local key pair there if absent. Add only the public key to the target account's `authorized_keys`, enforce SSH permissions, then test a non-interactive connection from the source machine.

## Keep conclusions evidence-based

Include exact timestamps with timezone when correlating reports such as “凌晨十二点半.” Distinguish observed facts from inference. When a command fails because the server has an old tool version, switch to a compatible equivalent rather than changing the server toolchain during unrelated work.
