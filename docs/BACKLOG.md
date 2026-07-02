# Backlog

**Status:** Living document — the persistent, prioritized backlog · **Last updated:** 2026-07-02
Priorities: **P0** = milestone-blocking · P1 = milestone-scoped · P2 = stretch/next.
Task IDs are stable (`M1-E2-T3` = milestone 1, epic 2, task 3). Completed work moves to §Done.

## M0 — Foundation (in flight)

Tracked in the working session; exit criteria in [ROADMAP.md](ROADMAP.md).

## M1 — Multi-agent engineering team v1

### E1 · Agent runtime (P0)
- M1-E1-T1 Define run/task/event domain model + Alembic migration (`agent_runs`, `agent_tasks`, `agent_events`, `artifacts`)
- M1-E1-T2 Supervisor StateGraph: route by task DAG, retries (max 2), failure states
- M1-E1-T3 Agent registry: role → system prompt + tool policy + model tier (config-driven)
- M1-E1-T4 Postgres checkpointing per run; resume-after-restart test
- M1-E1-T5 Run event bus: emit step events → Redis pub/sub → SSE endpoint `/v1/runs/{id}/events`
- M1-E1-T6 Per-run budget guard (token + cost caps from ADR-0006 accounting); abort + surface reason
- M1-E1-T7 arq worker entrypoint executing runs; graceful shutdown mid-run (checkpoint proof)

### E2 · Repo attach & workspaces (P0)
- M1-E2-T1 GitHub connect: PAT first (encrypted at rest), OAuth app flow next
- M1-E2-T2 `repositories` CRUD API + connect UI (list, add, status)
- M1-E2-T3 Workspace manager: clone → `.workspaces/<run>`, branch per run, cleanup policy
- M1-E2-T4 Path-jail module with symlink/UNC/traversal tests (security-critical, ADR-0008)

### E3 · Agent tools v1 (P0)
- M1-E3-T1 `list_dir`, `read_file` (size-capped), `search` (ripgrep vendored/fallback)
- M1-E3-T2 `apply_patch` (unified diff; reject fuzzy failures), `write_file` (jailed)
- M1-E3-T3 git tools: `branch`, `commit`, `diff_summary`
- M1-E3-T4 `open_pr` via GitHub API with generated description + DoD checklist
- M1-E3-T5 Task-board tools: `create_tasks`, `update_task_status` (writes `agent_tasks`)
- M1-E3-T6 Tool-call audit: every invocation → `agent_events` + `audit_logs`

### E4 · Specialist agents (P0)
- M1-E4-T1 PM agent: feature request → mini-PRD + task DAG (structured JSON output contract)
- M1-E4-T2 Backend / Frontend / DevOps engineer agents: task → edits + task summary
- M1-E4-T3 Reviewer agent: diff → verdict JSON (approve | request-changes + findings); one revision loop
- M1-E4-T4 Prompt files as versioned assets (`engine/agents/prompts/`), snapshot-tested

### E5 · Mission-control UI (P1)
- M1-E5-T1 Runs list + "new run" form (repo picker, request textarea)
- M1-E5-T2 Run detail: live agent timeline (SSE), task board, streamed agent output
- M1-E5-T3 Plan approval gate UI (approve / edit / reject → LangGraph interrupt resume)
- M1-E5-T4 Diff viewer + PR link panel
- M1-E5-T5 Run cost widget (tokens/cost per agent)

### E6 · Identity & keys (P1)
- M1-E6-T1 BYO provider keys: encrypted storage (AES-GCM), settings UI, engine resolution order (user key → env)
- M1-E6-T2 GitHub OAuth sign-in enabled end-to-end (needs OAuth app credentials)
- M1-E6-T3 Org switcher UI on top of better-auth organization plugin

### E7 · Eval seed (P1)
- M1-E7-T1 Fixture repo (small TS+Py service) committed under `fixtures/`
- M1-E7-T2 3 golden tasks (add endpoint, fix seeded bug, add config flag) + rubric
- M1-E7-T3 `scripts/eval_m1.py`: run team on golden tasks, score plan/diff/PR, CI-runnable with LLM_FAKE=0 gate

## M2+ parking lot (headline only)

- M2 indexing pipeline (tree-sitter TS/JS, Py → Java/Kotlin), hybrid retrieval + RRF,
  dependency graph, grounded citations UI, retrieval eval harness.
- M3 Docker sandbox runner, QA agent loops, webhook PR reviewer, secrets/dep scanning.
- CI e2e job using LLM_FAKE (Playwright against compose stack).
- LiteLLM proxy-server evaluation if non-engine callers appear (ADR-0006).
- Langfuse in compose + ModelRouter exporter (ADR-0010).

## Debt register

| Id | Debt | Why accepted | Revisit |
|---|---|---|---|
| D1 | pnpm hoisted linker (phantom deps possible) | OneDrive junction safety (ADR-0001) | if checkout leaves OneDrive |
| D2 | Engine trusts BFF JWT without mTLS | dev-only topology (ADR-0002) | M7 |
| D3 | No rate limiting on BFF/engine | single-user dev phase | M1-E6 / M7 |
| D4 | Playwright smoke not in CI (needs compose stack) | CI time budget | M1 |

## Done

- 2026-07-02 · M0 docs pack: PRD, OVERVIEW, ADR-0001…0010, ROADMAP, BACKLOG, SECURITY.
