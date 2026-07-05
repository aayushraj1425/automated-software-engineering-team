# Backlog

**Status:** Living document — the persistent, prioritized backlog · **Last updated:** 2026-07-05
Work is grouped into named workstreams per phase. Each workstream is marked
**blocking** (the phase cannot ship without it), **planned** (in scope for the phase),
or **stretch**. Pull requests reference items by name, e.g.
*"Backlog: Agent Runtime — Postgres checkpointing per run"*.
Completed work moves to §Done.

## Phase 0 — Foundation

Complete; exit criteria in [ROADMAP.md](ROADMAP.md), evidence in §Done.

## Phase 1 — Multi-Agent Engineering Team

### The 3-day plan (deadline 2026-07-07)

Goal: describe a feature → approve the plan → agents write the code → GitHub
pull request. Only what's needed for that demo; everything else waits.

- **Day 1 — done 2026-07-04:** runs API + in-process runner executing the
  Supervisor with stub agents; events saved to Postgres; `/runs` pages with a
  polling task board and timeline.
- **Day 2 (2026-07-06):** connect a GitHub repo; Product Manager agent plans →
  approval gate → engineer agents edit files through the jailed tools in a
  cloned workspace.
- **Day 3 (2026-07-07):** Reviewer agent + open the pull request; run the whole
  flow end to end on a small fixture repo; fix what breaks.

**Cut to make the deadline** (revisit after): Postgres checkpointing/resume,
Redis event streaming (polling instead), encrypted BYO keys + settings screen,
GitHub OAuth sign-in, organization switcher, the scripted evaluation harness.

The workstreams below remain the full Phase 1 map; the 3-day plan is the
subset being built now.

### Workstream: Agent Runtime (blocking)
- [x] Define the run/task/event domain model and its Alembic migration (`agent_runs`, `agent_tasks`, `agent_events`, `artifacts`) — design note: [architecture/AGENT_RUNTIME.md](architecture/AGENT_RUNTIME.md)
- [x] Supervisor graph: route work by task dependencies, retries (max 2), failure states
- [x] Agent registry: role → system prompt + tool policy + model tier (configuration-driven)
- [ ] Postgres checkpointing per run, with a resume-after-restart test
- [ ] Run event bus: step events → Redis pub/sub → streaming endpoint `/v1/runs/{id}/events`
- [ ] Per-run budget guard (token and cost caps per ADR-0006 accounting); abort with a surfaced reason
- [ ] Background worker entrypoint (arq) executing runs; graceful shutdown mid-run proving checkpoints work

### Workstream: Repository Connection & Workspaces (blocking)
- [ ] GitHub connection: personal access token first (encrypted at rest), OAuth app flow next
- [ ] Repositories API (create/list/status) and the connect screen
- [x] Workspace manager: clone into `.workspaces/<run>`, one branch per run, cleanup policy
- [x] Path-jail module with symlink/UNC/traversal tests (security-critical, ADR-0008); paths validated under both Windows and POSIX semantics

### Workstream: Agent Tools (blocking)
- [x] Read-side tools: list directory, read file (size-capped), search (plain-text scan; ripgrep upgrade pending)
- [x] Write-side tools: write file — jailed (apply-patch with unified diffs still pending)
- [x] Git tools: commit, diff against the run's base commit (branching is owned by the workspace manager)
- [ ] Open pull request via the GitHub API with a generated description and Definition-of-Done checklist
- [ ] Task-board tools: create tasks, update task status (writes `agent_tasks`)
- [ ] Tool-call audit: every invocation recorded to `agent_events` and `audit_logs`
- No arbitrary shell until the Phase 3 sandbox (ADR-0008).

### Workstream: Specialist Agents (blocking)
- [x] Product Manager agent: feature request → mini-specification + task breakdown (structured JSON contract, strict validation with one corrective round)
- [x] Backend, Frontend, and DevOps engineer agents: task → edits + task summary (shared tool loop; commit required before the summary)
- [ ] Reviewer agent: diff → verdict (approve / request changes with findings); one revision loop
- [ ] Prompt files as versioned assets (`engine/agents/prompts/`), snapshot-tested

### Workstream: Mission-Control Interface (planned)
- [x] Runs list and a "new run" form (repository URL, request text area)
- [x] Run detail: agent timeline and task board (polling; Redis streaming and per-agent output panes come later)
- [x] Plan approval gate: run pauses at `awaiting_approval`; approve/reject on the run page (in-place plan editing still pending)
- [ ] Diff viewer and pull-request link panel
- [ ] Run cost widget (tokens and cost per agent)

### Workstream: Identity & Keys (planned)
- [ ] Bring-your-own provider keys: encrypted storage (AES-GCM), settings screen, engine resolution order (user key, then environment)
- [ ] GitHub OAuth sign-in enabled end to end (needs OAuth app credentials)
- [ ] Organization switcher on top of the better-auth organization plugin

### Workstream: Evaluation Seed (planned)
- [ ] Fixture repository (small TypeScript + Python service) committed under `fixtures/`
- [ ] Three golden tasks (add an endpoint, fix a seeded bug, add a config flag) with a scoring rubric
- [ ] `scripts/eval_agent_team.py`: run the team against the golden tasks, score plan/diff/PR; CI-runnable behind a real-model gate

## Phase 2 and beyond (headlines only)

- Phase 2 — Repository Intelligence: indexing pipeline (tree-sitter for TypeScript/JavaScript
  and Python, then Java/Kotlin), hybrid retrieval with reciprocal-rank fusion, dependency
  graph, grounded citations in chat, retrieval evaluation harness.
- Phase 3 — Execution & QA: Docker sandbox runner, QA agent loops, webhook pull-request
  reviewer, secrets and dependency scanning.
- Continuous integration end-to-end job using the fake-model mode (Playwright against the compose stack).
- LiteLLM proxy-server evaluation if callers beyond the engine appear (ADR-0006).
- Langfuse in compose plus a ModelRouter trace exporter (ADR-0010).

## Debt register

| Debt | Why accepted | Revisit |
|---|---|---|
| pnpm hoisted linker (phantom dependencies possible) | OneDrive junction safety (ADR-0001) | if the checkout leaves OneDrive |
| Engine trusts the BFF's JWT without mutual TLS | development-only topology (ADR-0002) | Phase 7 |
| No rate limiting on the BFF or engine | single-user development phase | Identity & Keys workstream / Phase 7 |
| Playwright smoke not in CI (needs the compose stack) | CI time budget | Phase 1 |
| Deleting a repository cascades away its run history (`agent_runs` FK) | development-phase simplicity | retention/audit policy before any hosted deployment |

## Done

- 2026-07-02 · Phase 0 document pack: PRD, architecture overview, ADR-0001…0010, roadmap, backlog, security baseline.
- 2026-07-02 · Phase 0 walking skeleton verified end-to-end: compose services healthy
  (postgres on host port 5433), alembic up/down/up cycle + better-auth migration,
  engine 14/14 pytest + ruff + pyright, web 5/5 vitest + eslint + tsc + next build,
  shared OpenAPI types generated, Playwright smoke (sign-up → streamed chat →
  persistence across reload) green in fake-model mode.
- 2026-07-03 · Phase 0 shipped to GitHub: seven task-scoped commits pushed, CI green on
  main and pull request #1 (foundation PR with the Definition-of-Done checklist).
- 2026-07-03 · Agent Runtime — run/task/event domain model: design note
  (architecture/AGENT_RUNTIME.md with lifecycle + ER diagrams), `engine/db/enums.py`
  StrEnums, four new models, Alembic revision `0002_agent_runtime` (up/down/up verified
  on the dev database), five round-trip/cascade/constraint tests (engine suite 19/19).
- 2026-07-03 · Agent Runtime — agent registry: `engine/agents/registry.py` maps each
  role to a model tier, a declarative tool policy (deny-by-default per ADR-0008;
  reviewer and product manager are read-only), and a versioned prompt file under
  `engine/agents/prompts/`; six tests enforce the contract (engine suite 25/25).
- 2026-07-04 · Agent Runtime — supervisor graph: `engine/agents/supervisor.py` routes
  tasks by dependency and sequence, retries a failed task at most twice, fails the run
  with a saved reason and skips unstarted tasks; five routing tests (engine suite 30/30).
- 2026-07-04 · Day 1 of the 3-day plan: runs API (`engine/api/runs.py`), in-process
  runner with stub agents (`engine/agents/runner.py`), regenerated shared types, and
  the `/runs` pages (start form, task board, polling timeline). Engine 35/35, web 9/9,
  builds clean.
- 2026-07-05 · Repository Connection & Workspaces — path jail and workspace manager:
  `engine/workspace/jail.py` rejects escapes under both Windows and POSIX path rules
  (hardened after CI exposed a Linux backslash bypass); `engine/workspace/manager.py`
  shallow-clones per run, branches `asep/run-<id>`, records the base commit for diffs,
  and cleans up read-only git files on Windows.
- 2026-07-05 · Agent Tools — jailed toolbox: read/write/git tools behind an
  allow-list dispatcher (`engine/agents/tools.py`); tool failures return error text
  to the model instead of crashing the run.
- 2026-07-05 · Mission-Control Interface + Agent Runtime — plan approval gate:
  every run stops at `awaiting_approval`; `POST /v1/runs/{id}/decision` starts
  execution or cancels the run (wrong-state decisions get 409); the run page shows
  Approve/Reject with matching timeline entries. Engine 62 passed, web 9/9.
- 2026-07-05 · CI workflow actions bumped to current majors, ending the Node 20
  deprecation warnings.
