# Backlog

**Status:** Living document — the persistent, prioritized backlog · **Last updated:** 2026-07-08
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
- **Day 2 — done 2026-07-05:** repository cloned per run; Product Manager agent
  plans → approval gate → engineer agents edit files through the jailed tools
  in the cloned workspace.
- **Day 3 — code done 2026-07-05:** Reviewer agent (one revision loop), branch
  push, pull request via the GitHub API. Remaining: a real-model end-to-end run
  against a GitHub repository (needs `GITHUB_TOKEN` in `.env`); fix what breaks.

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
- [x] Per-run budget guard (cost cap per ADR-0006 accounting); the run fails with a surfaced reason before the next task starts
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
- [x] Open pull request via the GitHub API with a generated description (checklist note included; full Definition-of-Done template pending)
- [ ] Task-board tools: create tasks, update task status (writes `agent_tasks`)
- [x] Tool-call audit: every invocation recorded to `agent_events` (file contents summarized, never stored; `audit_logs` mirror pending)
- No arbitrary shell until the Phase 3 sandbox (ADR-0008).

### Workstream: Specialist Agents (blocking)
- [x] Product Manager agent: feature request → mini-specification + task breakdown (structured JSON contract, strict validation with one corrective round)
- [x] Backend, Frontend, and DevOps engineer agents: task → edits + task summary (shared tool loop; commit required before the summary)
- [x] Reviewer agent: diff → verdict (approve / request changes with role-tagged findings); one revision loop, second verdict is final
- [ ] Prompt files as versioned assets (`engine/agents/prompts/`), snapshot-tested

### Workstream: Mission-Control Interface (planned)
- [x] Runs list and a "new run" form (repository URL, request text area)
- [x] Run detail: agent timeline and task board (polling; Redis streaming and per-agent output panes come later)
- [x] Plan approval gate: run pauses at `awaiting_approval`; approve/reject on the run page (in-place plan editing still pending)
- [x] Pull-request link on the run page
- [x] Diff viewer: the run page shows everything the agents changed, colored by +/-
- [x] Run cost widget (token and cost totals in the run header)

### Workstream: Identity & Keys (planned)
- [ ] Bring-your-own provider keys: encrypted storage (AES-GCM), settings screen, engine resolution order (user key, then environment)
- [ ] GitHub OAuth sign-in enabled end to end (needs OAuth app credentials)
- [ ] Organization switcher on top of the better-auth organization plugin

### Workstream: Evaluation Seed (planned)
- [x] Fixture repository (small Python service + static web page, seeded bug) committed under `fixtures/demo-service/` — how-to: [EVALUATION.md](EVALUATION.md)
- [x] Three golden tasks (add an endpoint, fix the seeded bug, add a config flag) with a four-check scoring rubric
- [x] `apps/engine/scripts/eval_agent_team.py`: runs the team against the golden tasks and prints the scorecard (offline mode scores mechanics only; a real model adds the diff check)
- [ ] CI job running the real-model evaluation behind a provider-key gate

## Phase 2 — Repository Intelligence

Design note: [architecture/REPOSITORY_INTELLIGENCE.md](architecture/REPOSITORY_INTELLIGENCE.md).
Started 2026-07-06; blocking indexing and retrieval workstreams complete 2026-07-08
(exit criteria met). Java/Kotlin AST grammar remains a later, non-blocking item.

### Workstream: Indexing Pipeline (blocking)
- [x] Embeddings route: `ModelRouter.embed()` with `MODEL_EMBEDDING`; deterministic offline vectors under `LLM_FAKE`
- [x] `code_chunks` schema (pgvector `vector(768)`, migration 0004) and the line-window chunker
- [x] Indexer background task: clone → chunk → embed → replace the repository's chunks
- [x] AST-aware chunking with tree-sitter (Python, TypeScript/JavaScript/TSX, Java, Kotlin) — design note: [architecture/AST_CHUNKING.md](architecture/AST_CHUNKING.md)
- [x] Incremental re-indexing (changed files only) — design note: [architecture/INCREMENTAL_INDEXING.md](architecture/INCREMENTAL_INDEXING.md)
- [x] Approximate-nearest-neighbor index (hnsw) once repositories outgrow exact search — design note: [architecture/INCREMENTAL_INDEXING.md](architecture/INCREMENTAL_INDEXING.md)

### Workstream: Retrieval & Grounding (blocking)
- [x] Vector search endpoint `GET /v1/repositories/{id}/search` (cosine distance, top 8)
- [x] Hybrid retrieval: vector + Postgres full-text, fused with reciprocal-rank fusion (design note: [architecture/HYBRID_RETRIEVAL.md](architecture/HYBRID_RETRIEVAL.md))
- [x] Grounded chat: answers cite real files and line ranges (design note: [architecture/GROUNDED_CHAT.md](architecture/GROUNDED_CHAT.md))
- [x] Agents consume the index: a `search_code` tool in the shared read-tool set (design note: [architecture/AGENT_CODE_SEARCH.md](architecture/AGENT_CODE_SEARCH.md))
- [x] Retrieval evaluation: golden question set scored against a grep baseline (phase exit criterion)

### Workstream: Repository Screens (planned)
- [x] Repositories API: connect, list with index status and chunk counts
- [x] Repositories page: connect form, index/re-index button with live status, search box with file-and-line-cited results
- [x] Dependency / architecture graph views (Python, JS/TS/TSX, Java, Kotlin import resolution) (design note: [architecture/DEPENDENCY_GRAPH.md](architecture/DEPENDENCY_GRAPH.md))

## Phase 3 and beyond (headlines only)

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
- 2026-07-05 · Specialist Agents — real agents replace the stubs: Product Manager
  (strictly validated JSON plan, one corrective round), engineer agents on a shared
  tool loop (`engine/agents/loop.py`), workspace cloned at planning and reopened
  after approval (`agent_runs.base_sha`, migration 0003), token/cost totals per run.
  Engine 72 passed.
- 2026-07-05 · Reviewer + pull request: Reviewer agent verdict contract with one
  revision loop (`engine/agents/reviewer.py`), branch pushed to origin with the
  token kept out of logs, pull request opened via the GitHub API
  (`engine/github.py`), PR link on the run page, review/publish timeline events.
  End-to-end test proves a local repository gets the run branch pushed back.
  Engine 80 passed, web 9/9.
- 2026-07-05 · Run observability: every tool invocation lands in the timeline as a
  `tool.called` event (arguments summarized, file contents never stored), the per-run
  budget cap is enforced before each task with a surfaced reason, and the run page
  gained a colored diff viewer (`GET /v1/runs/{id}/diff`) plus token/cost totals.
  Engine 81 passed.
- 2026-07-06 · Evaluation seed: fixture service under `fixtures/demo-service/`
  (seeded out-of-range bug), three golden tasks with a scoring rubric
  (`engine/evaluation.py`), and the scorecard script
  (`scripts/eval_agent_team.py`) — offline run scores 3/3 on pipeline
  mechanics. Plain-language how-to in docs/EVALUATION.md. Engine 82 passed.
- 2026-07-06 · Phase 2 first slice: embeddings route in the ModelRouter,
  `code_chunks` schema (pgvector, migration 0004, up/down/up verified),
  line-window chunker, background indexer (clone → chunk → embed → store),
  and the repositories API (connect / list / index / search). Searching with
  a file's exact content ranks that file first at score ≈ 1.0 offline.
  Engine 85 passed.
- 2026-07-06 · Repositories page (`/repositories`): connect a repository, build
  its index with live status polling, and search it — results cite file, line
  range, language, and similarity score. Linked from the runs page.
- 2026-07-06 · Real-model hardening after the first live Gemini runs: the
  ModelRouter waits out provider rate limits (15s/30s/60s), the plan validator
  accepts the structured summary objects real models produce, and every
  evaluation run carries a $2 budget cap with per-task cost on the scorecard.
  Live run proved the loop: Gemini planned, coded, and committed the /stats
  golden task with a matching diff for $0.009 before the free-tier daily quota
  (20 requests) ended the session. Engine 86 passed.
- 2026-07-06 · Grounded chat with citations: chat accepts a `repository_id`,
  retrieves the eight closest chunks (shared `engine/indexing/retrieval.py`,
  also behind the search endpoint), grounds the model's prompt in the excerpts,
  streams a `citations` SSE event, and stores sources on the assistant message
  (`messages.citations`, migration 0005, up/down/up verified). The chat page
  gained a repository picker and a Sources list under grounded answers. Design
  note: architecture/GROUNDED_CHAT.md. Engine 89 passed, web 10/10.
- 2026-07-06 · Agents consume the index: `search_code` joins the jailed toolbox
  and the shared read-tool set (Product Manager, engineers, Reviewer). The tool
  resolves the run's repository through the workspace's run id — an agent can
  only search its own run's index — and answers with guidance instead of an
  error when no index exists. Role prompts explain when to prefer it over
  plain search. Design note: architecture/AGENT_CODE_SEARCH.md. Engine 91
  passed.
- 2026-07-08 · Hybrid retrieval: `retrieve_chunks` now runs a vector arm and a
  Postgres full-text arm (generated `content_tsv` column + GIN index, migration
  0006, up/down/up verified) and blends their rankings with reciprocal-rank
  fusion — exact identifiers and error strings surface even offline, while the
  displayed score stays cosine similarity. The signature is unchanged, so the
  search endpoint, grounded chat, and `search_code` gain hybrid ranking for
  free. Design note: architecture/HYBRID_RETRIEVAL.md.
- 2026-07-08 · Retrieval evaluation (Phase 2 exit criterion): a golden question
  set over the fixture service scored with recall and mean reciprocal rank
  against a grep baseline (`engine/retrieval_eval.py`, `scripts/eval_retrieval.py`).
  Offline the numbers measure the full-text arm plus fusion; a real embedding
  model shows the semantic lift. Engine 94 passed, 1 skipped.
- 2026-07-08 · AST-aware chunking: the chunker now splits larger Python,
  JavaScript, TypeScript, and TSX files by tree-sitter at their real
  boundaries — one chunk per top-level function or class, so a definition is
  never cut in half — while small files stay whole and unknown grammars or
  parser errors fall back to the version-1 line windows. The chunk record is
  unchanged, so the schema, embedder, and hybrid retrieval need no changes; a
  re-index picks up the better boundaries. Design note:
  architecture/AST_CHUNKING.md. Engine 96 passed, 1 skipped.
- 2026-07-08 · Dependency graph resolves Java and Kotlin imports: a first pass
  indexes each JVM file's `package` and declared types into a fully-qualified
  name → file map, then import statements resolve against it — wildcards link the
  whole package and static/member imports fall back to their declaring type,
  while third-party imports still drop out. Python and JS/TS keep their
  path-based resolution. Design note: architecture/DEPENDENCY_GRAPH.md. Engine
  107 passed, 1 skipped.
- 2026-07-08 · AST chunking extended to Java and Kotlin: the tree-sitter
  chunker now splits `.java`, `.kt`, and `.kts` files at their top-level types
  and functions (Java class/interface/enum/record, Kotlin class/function/object),
  keeping a definition whole instead of a blind line window; large types still
  window past the 200-line cap and unknown grammars keep the fallback. The
  dependency graph does not yet resolve Java/Kotlin imports. Design note:
  architecture/AST_CHUNKING.md. Engine 105 passed, 1 skipped.
- 2026-07-08 · Incremental re-indexing and HNSW index (Phase 2 indexing
  workstream complete): each source file's SHA-256 is recorded in `indexed_files`
  (migration 0008, up/down/up verified), so a re-index re-embeds only the files
  whose bytes changed, drops chunks of deleted files, and leaves unchanged files'
  rows untouched — the first index still does a full build. Import edges stay a
  full rebuild each run (cheap, no embedding call). An HNSW index over the
  embedding column (`vector_cosine_ops`, migration 0009) keeps cosine-distance
  vector search fast as repositories grow; retrieval uses it automatically with
  no code change. Design note: architecture/INCREMENTAL_INDEXING.md. Engine 103
  passed, 1 skipped.
- 2026-07-08 · Dependency / architecture graph: the indexer now also extracts
  first-party import edges with tree-sitter (`engine/indexing/dependency_graph.py`,
  Python + JS/TS/TSX, third-party packages dropped) and stores them in
  `code_edges` (migration 0007, up/down/up verified), rebuilt on every
  re-index. `GET /v1/repositories/{id}/graph` returns nodes with in/out degree
  plus edges; the repositories page draws it as a dependency-light circular
  SVG (nodes sized by how many files import them). Design note:
  architecture/DEPENDENCY_GRAPH.md. Engine 101 passed 1 skipped, web 12 passed.
