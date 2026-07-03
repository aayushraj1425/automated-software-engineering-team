# Backlog

**Status:** Living document — the persistent, prioritized backlog · **Last updated:** 2026-07-03
Priorities: **P0** = phase-blocking · P1 = phase-scoped · P2 = stretch/next.
Task IDs are stable and read *phase.epic.task* (`Task 1.2.3` = Phase 1, epic 2, task 3).
Completed work moves to §Done.

## Phase 0 — Foundation

Complete; exit criteria in [ROADMAP.md](ROADMAP.md), evidence in §Done.

## Phase 1 — Multi-Agent Engineering Team

### Epic 1.1 · Agent runtime (P0)
- Task 1.1.1 Define run/task/event domain model + Alembic migration (`agent_runs`, `agent_tasks`, `agent_events`, `artifacts`)
- Task 1.1.2 Supervisor StateGraph: route by task dependencies, retries (max 2), failure states
- Task 1.1.3 Agent registry: role → system prompt + tool policy + model tier (config-driven)
- Task 1.1.4 Postgres checkpointing per run; resume-after-restart test
- Task 1.1.5 Run event bus: emit step events → Redis pub/sub → SSE endpoint `/v1/runs/{id}/events`
- Task 1.1.6 Per-run budget guard (token + cost caps from ADR-0006 accounting); abort + surface reason
- Task 1.1.7 arq worker entrypoint executing runs; graceful shutdown mid-run (checkpoint proof)

### Epic 1.2 · Repository connection & workspaces (P0)
- Task 1.2.1 GitHub connect: personal access token first (encrypted at rest), OAuth app flow next
- Task 1.2.2 `repositories` CRUD API + connect UI (list, add, status)
- Task 1.2.3 Workspace manager: clone → `.workspaces/<run>`, branch per run, cleanup policy
- Task 1.2.4 Path-jail module with symlink/UNC/traversal tests (security-critical, ADR-0008)

### Epic 1.3 · Agent tools v1 (P0)
- Task 1.3.1 `list_dir`, `read_file` (size-capped), `search` (ripgrep vendored/fallback)
- Task 1.3.2 `apply_patch` (unified diff; reject fuzzy failures), `write_file` (jailed)
- Task 1.3.3 git tools: `branch`, `commit`, `diff_summary`
- Task 1.3.4 `open_pr` via GitHub API with generated description + Definition-of-Done checklist
- Task 1.3.5 Task-board tools: `create_tasks`, `update_task_status` (writes `agent_tasks`)
- Task 1.3.6 Tool-call audit: every invocation → `agent_events` + `audit_logs`
- (No arbitrary shell until the Phase 3 sandbox — ADR-0008.)

### Epic 1.4 · Specialist agents (P0)
- Task 1.4.1 Product Manager agent: feature request → mini-PRD + task breakdown (structured JSON output contract)
- Task 1.4.2 Backend / Frontend / DevOps engineer agents: task → edits + task summary
- Task 1.4.3 Reviewer agent: diff → verdict JSON (approve | request-changes + findings); one revision loop
- Task 1.4.4 Prompt files as versioned assets (`engine/agents/prompts/`), snapshot-tested

### Epic 1.5 · Mission-control UI (P1)
- Task 1.5.1 Runs list + "new run" form (repo picker, request textarea)
- Task 1.5.2 Run detail: live agent timeline (SSE), task board, streamed agent output
- Task 1.5.3 Plan approval gate UI (approve / edit / reject → LangGraph interrupt resume)
- Task 1.5.4 Diff viewer + PR link panel
- Task 1.5.5 Run cost widget (tokens/cost per agent)

### Epic 1.6 · Identity & keys (P1)
- Task 1.6.1 BYO provider keys: encrypted storage (AES-GCM), settings UI, engine resolution order (user key → env)
- Task 1.6.2 GitHub OAuth sign-in enabled end-to-end (needs OAuth app credentials)
- Task 1.6.3 Organization switcher UI on top of the better-auth organization plugin

### Epic 1.7 · Evaluation seed (P1)
- Task 1.7.1 Fixture repo (small TS+Python service) committed under `fixtures/`
- Task 1.7.2 Three golden tasks (add endpoint, fix seeded bug, add config flag) + rubric
- Task 1.7.3 `scripts/eval_agent_team.py`: run the team on golden tasks, score plan/diff/PR, CI-runnable behind an LLM_FAKE=0 gate

## Phase 2+ parking lot (headline only)

- Phase 2 indexing pipeline (tree-sitter TS/JS, Python → Java/Kotlin), hybrid retrieval
  + RRF, dependency graph, grounded citations UI, retrieval evaluation harness.
- Phase 3 Docker sandbox runner, QA agent loops, webhook PR reviewer, secrets/dependency scanning.
- CI end-to-end job using LLM_FAKE (Playwright against the compose stack).
- LiteLLM proxy-server evaluation if non-engine callers appear (ADR-0006).
- Langfuse in compose + ModelRouter exporter (ADR-0010).
- Bump GitHub Actions to next majors (checkout/setup-node/setup-uv emit Node 20 deprecation notices).

## Debt register

| Id | Debt | Why accepted | Revisit |
|---|---|---|---|
| D1 | pnpm hoisted linker (phantom deps possible) | OneDrive junction safety (ADR-0001) | if checkout leaves OneDrive |
| D2 | Engine trusts BFF JWT without mTLS | dev-only topology (ADR-0002) | Phase 7 |
| D3 | No rate limiting on BFF/engine | single-user dev phase | Epic 1.6 / Phase 7 |
| D4 | Playwright smoke not in CI (needs compose stack) | CI time budget | Phase 1 |

## Done

- 2026-07-02 · Phase 0 docs pack: PRD, OVERVIEW, ADR-0001…0010, ROADMAP, BACKLOG, SECURITY.
- 2026-07-02 · Phase 0 walking skeleton verified end-to-end: compose services healthy
  (postgres on host port 5433), alembic up/down/up cycle + better-auth migration,
  engine 14/14 pytest + ruff + pyright, web 5/5 vitest + eslint + tsc + next build,
  shared OpenAPI types generated, Playwright smoke (sign-up → streamed chat →
  persistence across reload) green with LLM_FAKE.
- 2026-07-03 · Phase 0 shipped to GitHub: 7 task-scoped commits pushed, CI green on
  main and PR #1 (foundation PR with Definition-of-Done checklist).
