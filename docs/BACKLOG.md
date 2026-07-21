# Backlog

**Status:** Living document — the persistent, prioritized backlog · **Last updated:** 2026-07-13
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
- [x] Postgres checkpointing per run, with a resume-after-restart test — the `agent_tasks` board is the checkpoint; startup recovery resumes interrupted runs from it (design note: [architecture/RUN_RECOVERY.md](architecture/RUN_RECOVERY.md))
- [x] Run event bus: step events → Redis pub/sub → streaming endpoint `/v1/runs/{id}/events/stream` (Postgres stays the record, Redis is the wake-up; design note: [architecture/RUN_EVENT_STREAMING.md](architecture/RUN_EVENT_STREAMING.md))
- [x] Per-run budget guard (cost cap per ADR-0006 accounting); the run fails with a surfaced reason before the next task starts
- [x] Background worker entrypoint (arq) executing runs; graceful shutdown mid-run proving checkpoints work (`RUN_QUEUE=arq` + `uv run arq engine.worker.WorkerSettings`; design note: [architecture/BACKGROUND_WORKER.md](architecture/BACKGROUND_WORKER.md))

### Workstream: Repository Connection & Workspaces (blocking)
- [x] Repository connection with credentials encrypted at rest: GitLab, Bitbucket, and Jira store a per-user token (AES-GCM, `integration_connections`); GitHub authenticates through the environment token (`GITHUB_TOKEN`) and public/local URLs need none — design note: [architecture/SOURCE_HOSTS.md](architecture/SOURCE_HOSTS.md). (A *per-user* GitHub personal-access token and the OAuth *app* flow for repo access stayed a later refinement — the env token covers the single-tenant case, and GitHub OAuth *sign-in* already ships.)
- [x] Repositories API (connect, list with index status and chunk counts) and the connect screen — `POST`/`GET /v1/repositories` plus the indexing, search, and dependency-graph endpoints, and the repositories page's connect form with live index status
- [x] Workspace manager: clone into `.workspaces/<run>`, one branch per run, cleanup policy
- [x] Path-jail module with symlink/UNC/traversal tests (security-critical, ADR-0008); paths validated under both Windows and POSIX semantics

### Workstream: Agent Tools (blocking)
- [x] Read-side tools: list directory, read file (size-capped), search — ripgrep when it is on PATH (fast, gitignore-aware), the Python scan as the no-dependency fallback, same output contract either way — design note: [architecture/RIPGREP_SEARCH.md](architecture/RIPGREP_SEARCH.md)
- [x] Write-side tools: write file and apply-patch, both jailed — `apply_patch` applies a unified diff via `git apply` (dry-run first, both prefix styles, whitespace-tolerant), so an edit is the size of the change instead of the whole file — design note: [architecture/APPLY_PATCH_TOOL.md](architecture/APPLY_PATCH_TOOL.md)
- [x] Git tools: commit, diff against the run's base commit (branching is owned by the workspace manager)
- [x] Open pull request via the GitHub API with a generated description (checklist note included; full Definition-of-Done template pending)
- [x] Task-board tools: engineers add newly discovered work with `add_task` (pending, next sequence — the supervisor merges and schedules it in the same run) and skip unnecessary pending tasks with `update_task_status` (skipped-only; refuses when unfinished work depends on the task) — design note: [architecture/TASK_BOARD_TOOLS.md](architecture/TASK_BOARD_TOOLS.md)
- [x] Tool-call audit: every invocation recorded to `agent_events` (file contents summarized, never stored; `audit_logs` mirror pending)
- No arbitrary shell until the Phase 3 sandbox (ADR-0008).

### Workstream: Specialist Agents (blocking)
- [x] Product Manager agent: feature request → mini-specification + task breakdown (structured JSON contract, strict validation with one corrective round)
- [x] Backend, Frontend, and DevOps engineer agents: task → edits + task summary (shared tool loop; commit required before the summary)
- [x] Reviewer agent: diff → verdict (approve / request changes with role-tagged findings); one revision loop, second verdict is final
- [x] Prompt files as versioned assets (`engine/agents/prompts/`), snapshot-tested: a checked-in SHA-256 snapshot fails the suite on any prompt drift and names the file; deliberate edits refresh the snapshot and commit both together — design note: [architecture/PROMPT_SNAPSHOTS.md](architecture/PROMPT_SNAPSHOTS.md)

### Workstream: Mission-Control Interface (planned)
- [x] Runs list and a "new run" form (repository URL, request text area)
- [x] Run detail: agent timeline and task board (live SSE stream with a polling fallback; per-agent output panes come later)
- [x] Plan approval gate: run pauses at `awaiting_approval`; approve/reject on the run page, and a nearly-right plan can be edited in place before approving — retitle, re-describe, or drop tasks (dangling dependencies cleaned; the edit lands on the timeline) — design note: [architecture/PLAN_EDITING.md](architecture/PLAN_EDITING.md)
- [x] Pull-request link on the run page
- [x] Diff viewer: the run page shows everything the agents changed, colored by +/-
- [x] Run cost widget (token and cost totals in the run header)

### Workstream: Identity & Keys (planned)
- [x] Bring-your-own provider keys: encrypted storage (AES-GCM), settings screen, engine resolution order (user key, then environment) — design note: [architecture/PROVIDER_KEYS.md](architecture/PROVIDER_KEYS.md)
- [x] GitHub OAuth sign-in surfaced in the UI: the server lists which providers have credentials (GitHub/Google/Microsoft), the sign-in and sign-up pages render one button per configured provider, and none configured means the email form alone — the OAuth app itself is operator setup, documented in the design note ([architecture/SIGN_IN_AND_ORGANIZATIONS.md](architecture/SIGN_IN_AND_ORGANIZATIONS.md))
- [x] Organization switcher on top of the better-auth organization plugin: settings-page panel lists/creates organizations and picks the active one (or personal); the BFF service JWT now carries the active organization as its `org` claim on every engine call (same design note)

### Workstream: Evaluation Seed (planned)
- [x] Fixture repository (small Python service + static web page, seeded bug) committed under `fixtures/demo-service/` — how-to: [EVALUATION.md](EVALUATION.md)
- [x] Three golden tasks (add an endpoint, fix the seeded bug, add a config flag) with a four-check scoring rubric
- [x] `apps/engine/scripts/eval_agent_team.py`: runs the team against the golden tasks and prints the scorecard (offline mode scores mechanics only; a real model adds the diff check)
- [ ] CI job running the real-model evaluation behind a provider-key gate

## Phase 2 — Repository Intelligence

Design note: [architecture/REPOSITORY_INTELLIGENCE.md](architecture/REPOSITORY_INTELLIGENCE.md).
Started 2026-07-06; blocking indexing and retrieval workstreams complete 2026-07-08
(exit criteria met). Java/Kotlin AST chunking and import resolution landed
2026-07-08 — see the checked items below.

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

## Phase 3 — Execution & QA

Complete 2026-07-10. Design note: [architecture/EXECUTION_AND_QA.md](architecture/EXECUTION_AND_QA.md).

### Workstream: Security Scanning (blocking)
- [x] Secrets scanner blocks a leaked secret before the pull request opens (phase exit criterion; design note: [architecture/SECRETS_SCANNING.md](architecture/SECRETS_SCANNING.md))
- [x] Dependency vulnerability scan of manifest changes (lockfiles / requirements) (design note: [architecture/DEPENDENCY_SCANNING.md](architecture/DEPENDENCY_SCANNING.md))

### Workstream: Sandbox Execution (blocking)
- [x] Docker sandbox runner: build and test the run's branch with no network egress (design note: [architecture/SANDBOX_EXECUTION.md](architecture/SANDBOX_EXECUTION.md))
- [x] Sandbox results land in the run timeline (pass/fail, captured output — the `sandbox.run` event)

### Workstream: QA Agent (blocking)
- [x] QA agent runs the project's tests in the sandbox and reads the failures (design note: [architecture/QA_AGENT.md](architecture/QA_AGENT.md))
- [x] Self-correction loop: failing tests route back to the QA agent with the failure text (bounded by `QA_MAX_ATTEMPTS`)

### Workstream: Webhook Reviewer (planned)
- [x] GitHub webhook receives pull-request events and queues a review (HMAC-signature auth; design note: [architecture/WEBHOOK_REVIEWER.md](architecture/WEBHOOK_REVIEWER.md))
- [x] Review agent comments on the pull request within five minutes (phase exit criterion)

## Phase 4 — Planning Suite

Complete 2026-07-10. Design note: [architecture/PLANNING_SUITE.md](architecture/PLANNING_SUITE.md).

### Workstream: Planning Domain & Backlog Store (blocking)
- [x] Define the durable, repository-scoped `work_items` model and its Alembic migration (title, description, kind, status, estimate, priority, dependencies, optional implementing-run link)
- [x] Work-items API: create / list / update / reorder under `/v1/repositories/{id}/work-items`
- [x] Task-board screen: reorderable backlog (drag to set order) with status, estimate, priority, milestone, and dependency badges; inline status and estimate edits

### Workstream: Roadmap Generation (blocking)
- [x] Scrum Master agent role: registry entry (prompt + tool policy + model tier) and roadmap generation that writes work items
- [x] Generate a milestone roadmap from a one-line goal plus repository context, saved to the backlog and shown on the task board (phase exit criterion)

### Workstream: Estimation (planned)
- [x] The agent assigns each work item a relative size (small / medium / large) with a one-sentence rationale, shown on the task board

### Workstream: Blocker Detection & Priority (planned)
- [x] Flag a work item whose dependency is unfinished; recommend the next unblocked, highest-value item (phase exit criterion; deterministic — `engine/planning/insights.py`)

## Phase 5 — Knowledge & Memory

Complete 2026-07-11 (exit criteria met; stretch item shipped the same day). Design note:
[architecture/KNOWLEDGE_AND_MEMORY.md](architecture/KNOWLEDGE_AND_MEMORY.md).

### Workstream: Knowledge Store (blocking)
- [x] `knowledge_items` model and its Alembic migration (repository-scoped; kind = decision / outcome / preference / note; embedding + generated full-text column; optional source-run link)
- [x] Write path: `remember()` embeds and stores one memory
- [x] Recall path: hybrid retrieval over memories (vector + full-text, reciprocal-rank fusion), mirroring the Phase 2 code retrieval

### Workstream: Automatic Capture (blocking)
- [x] A run reaching a terminal state writes its memory: the approved plan as a `decision`, the result (pull request or failure reason) as an `outcome` (phase exit criterion; capture never breaks a run)
- [x] Rejecting a plan at the approval gate records a `preference`

### Workstream: Memory Feeding Agent Context (blocking)
- [x] Product Manager planning recalls relevant memories into its prompt, with a `memory.recalled` timeline event (phase exit criterion)
- [x] Scrum Master roadmap generation recalls memories relevant to the goal alongside the repository file context

### Workstream: Knowledge API & Page (planned)
- [x] Knowledge API: list / add / delete / search under `/v1/repositories/{id}/knowledge`
- [x] Knowledge page: browse with kind badges and source-run links, search box, add-a-note form

### Workstream: Grounded Chat Reads Memory (stretch)
- [x] Repository chat blends recalled memories into its context next to code citations (`memory` SSE event; a "Remembered" list under the answer)

## Phase 6 — Workspace & Integrations

Design note (documentation slice): [architecture/DOCUMENTATION_SUITE.md](architecture/DOCUMENTATION_SUITE.md).
Started 2026-07-12 with the documentation generation suite (self-contained: no
external credentials, runs fully offline in fake-model mode). The workspace
panels and external integrations remain and are not yet scheduled.

### Workstream: Documentation Generation Suite (blocking)
- [x] Technical Writer agent role: registry entry (prompt + read-only tool policy + model tier)
- [x] `generated_documents` model and its Alembic migration (repository-scoped; kind = readme / api_reference / changelog / architecture; Markdown body; migration 0013, up/down/up verified)
- [x] Generator grounded in the index: file map + kind-seeded retrieved code + recalled memory → Markdown document; deterministic offline document under `LLM_FAKE`
- [x] Documents API: generate / list / delete under `/v1/repositories/{id}/documents`
- [x] Docs page (`/docs`): pick a document kind, generate it, browse / read / delete the results
- [x] Git-history changelog: the changelog kind now reads the repository's real commit history (bounded bare shallow clone, `date hash subject (author)` per line) and falls back to the snapshot summary honestly when the fetch fails — design note: [architecture/DOCUMENTATION_SUITE.md](architecture/DOCUMENTATION_SUITE.md)
- [x] In-place editing of a generated document: `PUT …/documents/{docId}` replaces the content (and optionally the title), the docs page gained an edit toggle with Save/Cancel, and regenerating still creates a new document so an edit is never silently overwritten — design note: [architecture/DOCUMENTATION_SUITE.md](architecture/DOCUMENTATION_SUITE.md)

### Workstream: Workspace Panels (planned)
- [x] Read-only file browser on the run page: list the run workspace's files and open any one read-only, jailed by `resolve_inside` — design note: [architecture/WORKSPACE_PANELS.md](architecture/WORKSPACE_PANELS.md)
- [x] In-browser editor + git status/commit panel: on a *finished* run (completed/failed) a file can be edited (jailed write) and the working tree committed; editing an in-flight run is a `409` so a human write never races the agent loop
- [x] Push a manual workspace commit back to the host: `POST /v1/runs/{id}/push` sends the run branch with the pipeline's own credential logic (GitLab connection, GitHub env token, plain otherwise), the git panel gained a Push branch button, and every push lands on the timeline as `branch.pushed` — design note: [architecture/WORKSPACE_PANELS.md](architecture/WORKSPACE_PANELS.md)
- [x] In-browser terminal wired to the Phase 3 sandbox: a command console (not a PTY) on finished runs — every command executes in a hardened session container with `--network none` from birth and the workspace *copied* in, so ADR-0008's line does not move — design note: [architecture/IN_BROWSER_TERMINAL.md](architecture/IN_BROWSER_TERMINAL.md)

### Workstream: External Integrations (planned)
- [x] Integrations foundation: encrypted per-user connection store (`integration_connections`, migration 0014, AES-GCM at rest), an adapter layer, dry-run mode, and an owner-scoped API (`/v1/integrations`) — design note: [architecture/EXTERNAL_INTEGRATIONS.md](architecture/EXTERNAL_INTEGRATIONS.md)
- [x] Chat: post run outcomes to Slack — a terminal run notifies the owner's Slack webhook and records an `integration.notified` timeline event; the settings page connects, tests, and removes the webhook
- [x] Issue trackers: push a work item to Linear (`issueCreate`) from the planning board, storing the issue link on the item, behind a tracker-agnostic dispatch (`engine/integrations/issues.py`) so Jira reuses it
- [x] Issue trackers: add Jira as a second tracker behind the same dispatch (REST `/rest/api/3/issue`, HTTP-Basic auth, ADF description); the planning board pushes to each connected tracker
- [x] Source hosts: a run on a `gitlab.com` repository pushes its branch and opens a merge request with the owner's encrypted GitLab token; the publish step is host-aware and the GitHub path is unchanged — design note: [architecture/SOURCE_HOSTS.md](architecture/SOURCE_HOSTS.md)
- [x] Source hosts: Bitbucket behind the same host-aware publish seam — `bitbucket.org` detection, an encrypted username + app-password connection, the https push authenticates with it, and a finished run opens a Bitbucket pull request; credential resolution now lives once in `engine/integrations/hosts.py`, shared by the pipeline and the manual Push branch button — design note: [architecture/SOURCE_HOSTS.md](architecture/SOURCE_HOSTS.md)
- [x] Source hosts: self-hosted GitLab — the connection's `base_url` names the instance for detection too, so a run on `https://git.acme.dev/…` pushes with the connection's token and opens its merge request on that instance; self-hosted Bitbucket documented out (Server/Data Center is a different API, not a different host)

## Phase 7 — Production Hardening

Phase plan: [architecture/PRODUCTION_HARDENING.md](architecture/PRODUCTION_HARDENING.md).
Started 2026-07-13 with observability — the workstream everything else in the
phase (alerting, benchmarks, K8s probes) leans on.

### Workstream: Observability (blocking)
- [x] OpenTelemetry SDK wired per ADR-0010: instrumentation through the OTel API unconditionally (no-op by default), `OTEL_ENABLED=1` + `OTEL_EXPORTER_OTLP_ENDPOINT` install the SDK and export via OTLP/HTTP
- [x] Request spans (route template + status, `/healthz` excluded) and request count/duration metrics from a pure-ASGI middleware
- [x] LLM spans on every ModelRouter call (tier, model, tokens, cost) and `run.plan` / `run.execute` spans tying an agent run together
- [ ] Alerting rules (error rate, p95 latency, token spend) once real traffic calibrates them

### Workstream: Hardening the Seams (planned)
- [x] Rate limiting on the engine API: per-caller token bucket (verified JWT subject, IP fallback), 429 + `Retry-After`, off by default (`RATE_LIMIT_PER_MINUTE=0`) — design note: [architecture/RATE_LIMITING.md](architecture/RATE_LIMITING.md)
- [x] Redis-backed shared rate window (`RATE_LIMIT_SHARED=1`): one token bucket across replicas, taken by an atomic Lua script, degrading to the per-replica bucket if Redis is down — design note: [architecture/RATE_LIMITING.md](architecture/RATE_LIMITING.md)
- [ ] BFF→engine trust: mutual TLS or network policy (ADR-0002 debt)

### Workstream: Backups & Disaster Recovery
- [x] Scheduled Postgres dumps and a **tested** restore path, with a written recovery runbook — design note: [architecture/BACKUPS_AND_RECOVERY.md](architecture/BACKUPS_AND_RECOVERY.md), runbook: [runbooks/DISASTER_RECOVERY.md](runbooks/DISASTER_RECOVERY.md)
- [ ] Ship dumps off-host (S3/MinIO or a volume the K8s CronJob mounts) — a local backup directory burns down with the machine (Deploy workstream)

### Workstream: RBAC & Row-Level Security
- [x] Row-level security on the ownership-carrying tables (`repositories`, `conversations`, `agent_runs`, `provider_keys`, `integration_connections`): API sessions are pinned to the verified JWT subject, and Postgres itself refuses other users' rows — design note: [architecture/ROW_LEVEL_SECURITY.md](architecture/ROW_LEVEL_SECURITY.md)
- [x] Organization-aware sharing: repositories and agent runs created under an active organization are visible — and writable — to whoever has that organization active; the rule lives once in `engine/db/visibility.py` for the route filters and in the RLS policies (`app.org_id` alongside `app.user_id`) for Postgres itself; conversations, provider keys, and integrations stay personal — design note: [architecture/ORGANIZATION_SHARING.md](architecture/ORGANIZATION_SHARING.md)
- [x] Deny-by-default policies with an explicit service context: a session that asserts neither a user pin nor `app.service='1'` reads and writes zero rows; `session_scope()` is the documented internal entry point and the alembic connection asserts the context for data migrations — a forgotten pin is now loud, not a leak
- [x] Separate non-owner database role for the API: the policies' service clause requires *being* the `asep` role, and user-pinned sessions connect as the DML-only `asep_api` (`DATABASE_URL_API`) — an attacker with raw SQL on an API session cannot claim the service context or touch a policy; the whole test suite runs in two-role mode
- [x] Subquery policies for the child tables — all ten (`messages`, `agent_tasks`, `agent_events`, `artifacts`, `code_chunks`, `code_edges`, `indexed_files`, `work_items`, `knowledge_items`, `generated_documents`) are now visible exactly when their parent row is, via an `EXISTS` that runs under the parent's own policy; org sharing flows through automatically and retrieval latency is unchanged
- [x] Organization members, invitations, and roles — the settings panel manages members (invite by email with a copyable accept link, change member/admin roles, remove) via the better-auth organization plugin, and the engine enforces one destructive rule: disconnecting a teammate's shared repository or removing the team's provider key takes an organization admin, carried as a BFF-verified `org_role` claim signed only on those routes — design note: [architecture/ORGANIZATION_ROLES.md](architecture/ORGANIZATION_ROLES.md)

### Workstream: Deploy
- [x] Production images (engine: API/worker/migrations from one image; web: Next.js standalone) and a Helm chart — `/healthz` probes, pre-upgrade migration Job, one Secret mirroring `.env`, engine ClusterIP-only; CI lints and renders the chart — design note: [architecture/KUBERNETES_DEPLOY.md](architecture/KUBERNETES_DEPLOY.md)
- [ ] Revisit the chart's placeholder resource limits once the benchmarks measure the hot paths
- [ ] In-cluster QA sandbox (pods have no Docker daemon; needs DinD, Kata, or a remote builder — `SANDBOX_ENABLED=0` in chart defaults until then)
- [ ] Persistent volume template for `BACKUP_DIR` when `BACKUP_ENABLED=1` on the worker (pairs with shipping dumps off-host)

### Workstream: Benchmarks & Security Audit
- [x] Performance baselines for indexing, retrieval, and the run pipeline — offline CLI (`python -m engine.benchmark`), first baseline table recorded in the design note: [architecture/BENCHMARKS.md](architecture/BENCHMARKS.md)
- [x] Checklist audit of the security boundaries — every boundary verified with code evidence, one finding fixed inline (the route-table auth sweep test), the rest logged: [security/SECURITY_AUDIT.md](security/SECURITY_AUDIT.md)
- [x] Loud startup warning when `ENGINE_ENCRYPTION_KEY` is unset and secrets fall back to the key derived from `ENGINE_SERVICE_SECRET` — API lifespan and worker both warn at boot (audit finding 2)
- [x] Webhook replay/dedupe guard — queued `X-GitHub-Delivery` ids are remembered (bounded, in-process) and a redelivery is ignored instead of re-reviewed (audit finding 3)

## Beyond Phase 3 (headlines only)

- ~~Continuous integration end-to-end job using the fake-model mode (Playwright against the compose stack)~~ — landed 2026-07-19 ([CI_END_TO_END_SMOKE.md](architecture/CI_END_TO_END_SMOKE.md)).
- LiteLLM proxy-server evaluation if callers beyond the engine appear (ADR-0006).
- Langfuse in compose plus a ModelRouter trace exporter (ADR-0010).

## Debt register

| Debt | Why accepted | Revisit |
|---|---|---|
| pnpm hoisted linker (phantom dependencies possible) | OneDrive junction safety (ADR-0001) | if the checkout leaves OneDrive |
| Engine trusts the BFF's JWT without mutual TLS | development-only topology (ADR-0002) | Phase 7 |
| Rate limiting's shared window closed 2026-07-21 (`RATE_LIMIT_SHARED` puts one bucket in Redis across replicas, degrading to per-replica if Redis is down — [RATE_LIMITING.md](architecture/RATE_LIMITING.md)); the BFF itself stays unlimited | engine ceiling covers BFF-proxied traffic | per-route tiers if real traffic shows the shape |
| ~~Playwright smoke not in CI (needs the compose stack)~~ — closed 2026-07-19: a CI job runs the smoke against the compose stack in fake-model mode ([CI_END_TO_END_SMOKE.md](architecture/CI_END_TO_END_SMOKE.md)) | — | a production-build smoke (the Docker images, not dev servers) can come with hosted multi-tenancy |
| ~~Deleting a repository cascades away its run history~~ — closed 2026-07-18: the FK is `SET NULL`, runs survive a disconnect ([RUN_HISTORY_RETENTION.md](architecture/RUN_HISTORY_RETENTION.md)) | — | an automatic pruning *schedule* can come with hosted multi-tenancy |

## Done

- 2026-07-21 · Board honesty pass + operator handoff. Every self-contained
  engineering item is now shipped, so the board was reconciled against the
  code: two stale-open checkboxes in the Repository Connection workstream are
  corrected — the Repositories API and connect screen have shipped since
  Phase 2, and repository *connection* works end to end (GitLab/Bitbucket/Jira
  store an encrypted per-user token, GitHub uses the environment token; a
  per-user GitHub PAT and the OAuth *app* flow stayed a deliberate later
  refinement). What genuinely remains is all operator-gated — a secret, a
  running piece of infrastructure, or a decision only the operator can make —
  so it is gathered into one handoff note with each item's prerequisite spelled
  out: [OPERATOR_HANDOFF.md](OPERATOR_HANDOFF.md).

- 2026-07-21 · The rate-limiter's window can span every replica —
  `RATE_LIMIT_SHARED=1` moves the token bucket into Redis. The in-process
  buckets meant the effective ceiling was `limit × replicas`; once the chart
  scales the engine out, that is the wrong number. The shared path runs the
  same refill-then-take arithmetic as the in-process bucket, but as one atomic
  Lua script inside Redis (the wall clock is passed in, so it does not depend
  on Redis's own clock), keyed the same way — `user:<sub>` for a verified
  token, `ip:<client>` otherwise — with a TTL just past a full refill so idle
  callers expire on their own and the shared path needs no pruning sweep. A
  Redis outage degrades to the same in-process bucket the default path uses
  and warns once: the ceiling drops back to per-replica, never a hard
  dependency and never a 429 storm. Off by default, so dev and the suite touch
  Redis only in the tests that opt in. `ratelimit.py` split into a
  `LocalLimiter` and a `SharedLimiter` behind the same async `take`; the
  middleware picks one per request. Design note:
  [architecture/RATE_LIMITING.md](architecture/RATE_LIMITING.md); debt-register
  row struck; `.env.example` gained `RATE_LIMIT_SHARED`. Verified: engine
  ruff/pyright clean, full suite 409 passed / 1 skipped — three new tests (the
  shared window enforced through a live Redis, separate callers, and the
  degrade-to-local path with a stubbed dead Redis so it runs in CI without one;
  the live tests build their client on the test's own loop, since the default
  fixture loop scope is the session).

- 2026-07-20 · The Playwright smoke runs in CI, it caught a migration bug on
  its first real run, and the `git_branch` ghost is gone — two debt-register
  rows closed plus one silent data-layer bug. A new CI job runs the existing
  end-to-end spec (sign up → message → streamed fake-model reply → reload
  proves persistence) the exact way a developer does: the dev compose stack
  on a fresh volume (postgres-init creates the roles), `pnpm db:migrate`,
  and Playwright's own `webServer` blocks booting the engine
  (`LLM_FAKE=1`) and the web dev server — no secrets, no sleep-and-hope
  steps, Chromium only, traces kept on failure and uploaded as an
  artifact. The config gained `forbidOnly` and stops reusing servers on CI.
  **The bug the smoke caught:** running it against a *real* migrated
  database exposed that `alembic upgrade head` had been silently rolling
  back since migration 0018. `env.py` opens the migration transaction with
  `set_config('app.service', …)` (the DDL and the RLS service context must
  share one transaction), which meant alembic's `begin_transaction()`
  joined that transaction instead of owning it — and a joined transaction is
  never committed on exit. Every upgrade ran, logged success, exited zero,
  and rolled back; the test suite never noticed because `conftest` builds
  its schema with `create_all`, not alembic. One-line fix: commit the
  transaction we left open. Separately, the agent registry no longer
  declares `git_branch` — never implemented, and rightly so: the pipeline
  creates the run's branch itself (`workspace/manager.py`) and a branch
  tool would only let an agent wander off the branch the reviewer and the
  PR watch. The registry test now asserts the stronger property: every tool
  a role declares is implemented, so a policy typo is a loud failure instead
  of a tool that silently never appears. Design note:
  [architecture/CI_END_TO_END_SMOKE.md](architecture/CI_END_TO_END_SMOKE.md).
  Verified: engine ruff/pyright clean, full engine suite 406 passed /
  1 skipped (including the new declared-tools-are-implemented test); the
  smoke passes locally against the compose stack the same way the CI job
  runs it (1 passed), and `alembic current` now reports `0022 (head)` after
  an upgrade.

- 2026-07-19 · Organization members, invitations, and roles — the follow-up
  the org-sharing note promised ("roles are a later slice"). The settings
  panel now manages the active organization: invite by email with a role
  (member/admin), copy the accept link and share it yourself (no email
  provider is wired — the note says so in the UI), a new
  `/accept-invitation/[id]` page accepts or declines and switches the
  workspace, owners/admins change roles or remove members — all through the
  better-auth organization plugin, which enforces its own permission rules
  server-side (the panel adds UI, not policy). The engine got exactly one
  rule of its own: *members create and work; destroying a shared thing you
  did not create takes an admin*. A new `org_role` JWT claim — signed only
  by the two destructive BFF routes, read fresh from
  `auth.api.getActiveMember` at request time, never cached in the session —
  gates disconnecting a teammate's shared repository (403 for a plain
  member, 204 for an admin or the connector) and removing the team's shared
  provider key (its contributor or an admin). `Principal` grew
  `org_role`/`is_org_admin`; `signServiceToken` takes an options bag and
  refuses to sign a role without an org. Design note:
  [architecture/ORGANIZATION_ROLES.md](architecture/ORGANIZATION_ROLES.md);
  the org-sharing note's "equal collaborators" boundary updated in place.
  Verified: engine 405 passed / 1 skipped (two new gate tests in
  `test_org_sharing.py`); web lint, typecheck, and 21 tests green
  (new service-token test: the role signs only when asked, never without
  an org).

- 2026-07-19 · The non-owner API database role — the RLS story's final
  piece, closing the audit's last logged boundary. The policies' service
  clause now requires *being* the service role, not just setting a GUC:
  `app.service='1' AND current_user='asep'`. User-pinned sessions (the
  request dependency and `session_scope(user_id=…)`) connect as `asep_api`
  when `DATABASE_URL_API` is set — a plain NOSUPERUSER login role with
  DML-only grants that cannot drop or disable a policy and gains nothing
  from the flag; an attacker with raw SQL on an API session is confined to
  the pinned user's rows, full stop. Proven directly: an `asep_api`
  session that sets the flag reads zero rows while the owner role with the
  same flag reads everything. Operationally seamless: fresh volumes create
  the role (postgres-init), CI creates it beside `asep`, the *entire test
  suite now runs in two-role mode* (conftest creates the role and routes
  every pinned session through it — 400+ existing tests re-verify the
  separation for free), migration `0022` applies grants (skipped quietly
  without the role — single-role mode keeps working), and `.env.example`
  documents the second URL. Design note: architecture/ROW_LEVEL_SECURITY.md
  (privilege separation); audit updated in place. Engine 403 passed,
  1 skipped; web untouched.
- 2026-07-19 · The in-browser terminal — the last Phase 6 item, and the
  phase is complete. A command console, not a PTY: one command in, its
  output back, on finished runs only (the same 409 as every write panel).
  ADR-0008's line does not move — every command executes inside a session
  container with the QA sandbox's hardening (caps dropped,
  no-new-privileges, memory/CPU/pids limits) plus one stricter choice:
  `--network none` from birth — the terminal has no install phase and no
  egress, ever (installing dependencies is the pipeline sandbox's job).
  The workspace is *copied* in, never mounted: the terminal is a scratch
  copy, and the panel says so — edits there never reach the real files.
  Sessions are lazy (created on the first command), persistent between
  commands, and reaped lazily after 30 minutes or an explicit Reset; a
  timed-out command discards the session rather than leaving it wedged;
  containers carry `asep.terminal=1` so orphans are one docker command
  away. `SANDBOX_ENABLED=0` or no Docker refuses with a plain-language
  reason, never host execution. Design note:
  architecture/IN_BROWSER_TERMINAL.md. Engine 402 passed, 1 skipped (8
  new tests over a scripted fake docker: hardening flags asserted on the
  actual run call, session reuse, TTL refresh, timeout reset, the
  disabled-sandbox refusal, and the API's 409/404 guards — the auth sweep
  covers the new routes automatically); web 20 passed.
- 2026-07-19 · Organization-shared provider keys: a team no longer needs
  every member to paste the same key. Sharing is opt-in per key — a secret
  is never shared by default: the settings page gained a "share with your
  active organization" checkbox, `PUT /v1/provider-keys/{provider}` takes
  `share_with_organization` (400 without an active org), and
  `DELETE ?shared=true` removes the team key. One org key per
  (organization, provider) and one personal key per (user, provider) —
  partial unique indexes replace the old constraint (migration `0021`,
  which also gives `provider_keys` the org-shared RLS policy, so Postgres
  itself scopes a shared key to whoever has that organization active).
  Resolution order: personal → organization → `.env` — your own key
  always outranks the team's — carried by the JWT's `org` claim at the
  API entry points and the run's own `org_id` in the runner. Members are
  equal collaborators: any member sees the team key (last four + a
  "team key" tag, never the value), replaces it, or removes it. Design
  note: architecture/PROVIDER_KEYS.md (organization-shared keys);
  ORGANIZATION_SHARING.md's table updated. Engine 394 passed, 1 skipped
  (3 new tests: member visibility/replace/remove, the no-org 400, and
  personal-beats-team resolution incl. the org-inactive fallback); web
  20 passed.
- 2026-07-18 · In-place plan editing, closing the approval gate's oldest
  pending note: a nearly-right plan no longer forces a reject-and-replan
  round trip. `PUT /v1/runs/{id}/plan` — only while `awaiting_approval`
  (409 otherwise, the same closed-gate shape as everywhere) — lets the
  human retitle, re-describe, or drop tasks: at least one must remain
  (dropping everything is Reject's job), a dropped task's id disappears
  from every survivor's `depends_on` so the board can never deadlock on a
  ghost, `run.plan`'s title list follows the board, and `plan.edited`
  lands on the timeline with what changed. Description semantics are
  non-destructive: omitted leaves it alone, empty clears it (a bug the
  tests caught — the first draft silently cleared descriptions on
  title-only edits). Deliberately no adding tasks (mid-run the agents add
  their own; a missing-from-the-start task means the plan deserves
  rejection), no role changes, no reordering. The run page's gate gained
  Edit plan → per-task title input, description textarea, drop/keep
  toggle → Save; approving then executes exactly the edited board.
  Design note: architecture/PLAN_EDITING.md. Engine 391 passed, 1 skipped
  (3 new tests: edit+drop then the edited board runs to completion,
  dangling-dependency cleanup proven by a no-deadlock run, and the
  guardrails — all-dropped 400, foreign task id 400, post-approval 409);
  web 20 passed.
- 2026-07-18 · Run-history retention and repository disconnect, closing
  the debt-register item flagged "before any hosted deployment". The rule:
  deleting a repository removes the *repository's* data, never the *runs'*
  data. `agent_runs.repository_id` went from `ON DELETE CASCADE` to
  nullable `SET NULL` (migration `0020`, whose downgrade honestly deletes
  detached runs — the exact loss the upgrade prevents), so a run outlives
  its repository with timeline, task board, audit events, and cost totals
  intact; the runs list shows "(repository disconnected)" where the URL
  was. Disconnect itself now exists — `DELETE /v1/repositories/{id}` with
  the usual visibility scoping, refused with a 409 while runs are active
  (the runner never sees a vanished repository mid-flight), and a
  disconnect action with a plain-language confirm on the repositories
  page. Repository-scoped data (index, work items, knowledge, documents)
  cascades as before; memory capture skips detached runs; the benchmark
  harness deletes its synthetic runs explicitly now that the cascade no
  longer does. Design note: architecture/RUN_HISTORY_RETENTION.md. Engine
  388 passed, 1 skipped (3 new tests: history survives with full record,
  409 while active then 204 after finishing, intruder 404); web 19 passed.
- 2026-07-18 · Self-hosted GitLab, closing the Source Hosts workstream:
  the connection's `base_url` now names the instance for *detection* as
  well as for the API. `connection_repo_path` matches a repository URL
  against gitlab.com or the connection's own host (https and ssh forms,
  suffix-spoofing hosts rejected); `host_connection` asks the connection
  when a URL is on no SaaS host (GitHub URLs never consult it), and
  `open_merge_request` resolves the project path the same way — so a run
  on `https://git.acme.dev/team/demo` pushes with the connection's token
  and opens its merge request on that instance. Self-hosted Bitbucket
  documented out on purpose: Server/Data Center speaks a different API
  (1.0-style REST, different auth) — a different protocol, not a
  different host. Design note: architecture/SOURCE_HOSTS.md (updated in
  place). Engine 385 passed, 1 skipped (3 new tests); web untouched.
- 2026-07-17 · Ripgrep-backed search: the agents' plain-text `search` tool
  uses ripgrep when it is on PATH — fixed-string, case-insensitive, `.git`
  excluded, size-capped exactly like the Python scan, plus one deliberate
  improvement: `.gitignore` is respected, so vendored dependencies and
  build output no longer drown the results. The Python scan stays as the
  no-dependency fallback, and both engines honor one output contract
  (`path:line: content`, 50-result cap, same empty-result message) —
  proven by a test that runs the *same query through both engines* and
  asserts byte-identical output (on this machine, against VS Code's
  bundled rg; on CI, the preinstalled one; skips cleanly where neither
  exists). No regex exposure — the tool stays plain-text; `search_code`
  remains the meaning-based arm. Design note:
  architecture/RIPGREP_SEARCH.md. Engine 382 passed, 1 skipped; web
  untouched.
- 2026-07-17 · The apply_patch tool: engineers no longer rewrite a whole
  file for a two-line fix. The long-declared name is now bound — a unified
  diff goes through two jails (every path in the diff through
  `resolve_inside` before git ever sees it, then `git apply`'s own
  outside-the-tree refusal), a `--check` dry run makes application
  all-or-nothing, prefix detection accepts both `a/ b/` and bare-path
  diffs, and `--ignore-whitespace` absorbs the whitespace drift models
  introduce. A context mismatch returns guidance the model can act on
  (re-read, regenerate) instead of a stack trace; no fuzzy or three-way
  application by design — that is how silent corruption ships. write_file
  stays for new and small files; the offline pipeline is untouched. The
  schema teaches the model when to prefer which. Design note:
  architecture/APPLY_PATCH_TOOL.md. Engine 381 passed, 1 skipped (6 new
  tests: both prefix styles, file creation, jail escape refused, mismatch
  guidance, non-diff rejected); web untouched.
- 2026-07-17 · Child-table row-level security: the last tables guarded only
  by convention now carry policies of their own. All ten children —
  `messages`, `agent_tasks`, `agent_events`, `artifacts`, `code_chunks`,
  `code_edges`, `indexed_files`, `work_items`, `knowledge_items`,
  `generated_documents` — are visible exactly when their parent row is: an
  `EXISTS` subquery that runs under the *parent's* policy, so the owner/org
  logic stays written once and org sharing flows through automatically (an
  org member sees the tasks of a shared run; a pinned session cannot attach
  rows to a stranger's run — WITH CHECK). The explicit service context
  skips the subquery; `audit_logs` stays policy-free on purpose (no owning
  parent, service-written). Retrieval benchmark re-run after the policies:
  p50 103.2 ms / p95 115.1 ms — unchanged from the baseline (the benchmark
  exercises the service path; the user path adds one primary-key EXISTS).
  Migration `0019_child_table_rls`; design note updated in place. Engine
  374 passed, 1 skipped, one unrelated Redis-fallback timing flake that
  passes in isolation; web untouched.
- 2026-07-17 · Row-level security is now deny-by-default: the audit's
  biggest accepted boundary — "unset context is trusted" — is closed. The
  policies require an explicit assertion: API sessions pin `app.user_id`
  (+ `app.org_id`) as before, internal paths get `app.service='1'` set by
  `session_scope()` (the documented entry point the runner, webhooks, and
  workers already use — zero call-site churn), and the alembic connection
  asserts the context so data migrations keep working. A session with no
  context at all — the exact shape of a forgotten pin — reads zero rows,
  updates zero rows even by primary key, and cannot insert; forgetting
  context is loud, not a leak. `pg_restore` still works because policies
  are recreated after the data loads (proven by the restore-from-a-real-
  dump test in the suite). Honest boundary kept: the flag guards against
  our own bugs, not a database attacker who can run arbitrary SQL — the
  separate non-owner API role stays on the backlog as its own item.
  Migration `0018_rls_deny_by_default` (downgrade restores 0017's
  trusted-unset policies); audit report and design note updated in place.
  Engine 371 passed, 1 skipped; web untouched.
- 2026-07-17 · Bitbucket as the third source host, behind the seam GitLab
  cut: `parse_bitbucket_repo` recognizes `bitbucket.org/workspace/repo`,
  the settings page connects a username + app password (encrypted at rest,
  the label shows the username only), the https push authenticates with
  that pair through the same `push_branch` credential, and a finished run
  opens a Bitbucket pull request via the 2.0 API (Basic auth; dry-run
  placeholder keeps it offline-testable). Credential resolution got its
  own home — `engine/integrations/hosts.py` (`host_connection` +
  `push_credential`) — used by both the pipeline's publish and the run
  page's manual Push branch button, so the two can never drift. Bitbucket
  is a git host, not an issue tracker (asserted in tests like GitLab).
  Every `IntegrationKind` now has an adapter, so the deny-by-default gate
  test proves itself with a kind that does not exist. Design note:
  architecture/SOURCE_HOSTS.md (updated in place). Engine 370 passed,
  1 skipped (7 new tests); web 19 passed.
- 2026-07-17 · In-place document editing: a generated document is a
  starting point, not gospel — the person who knows the project can now
  correct the prose where the model got it wrong. `PUT
  /v1/repositories/{id}/documents/{docId}` replaces the content (size-
  capped like generation) and optionally the title, with the same
  visibility scoping as every other document call; the docs page's open
  document gained an edit toggle — textarea, Save/Cancel, nothing more.
  Regenerating a kind still creates a *new* document, so a human edit is
  never silently overwritten by the model; last save wins (no versioning —
  logged as a boundary). Design note: architecture/DOCUMENTATION_SUITE.md
  (updated in place). Engine 364 passed, 1 skipped (3 new tests: edit
  roundtrip with title kept on content-only saves, unknown document 404,
  intruder 404); web 19 passed.
- 2026-07-17 · Git-history changelog: a snapshot is not a changelog — the
  changelog document kind now reads the repository's real commit history.
  `engine/docs/git_history.py` fetches the last 100 commits with a
  temporary bare shallow clone (history only, no working tree, removed
  afterwards; the URL passes the same `ensure_cloneable_url` hygiene as
  every clone) and hands the writer one `date hash subject (author)` line
  per commit, so the model groups real changes under real dates instead of
  inventing versions. When the fetch fails — private remote, network down —
  the changelog falls back to the snapshot summary and says so in its
  opening line; the fetch is anonymous by design (credential helpers
  disabled, so an unreachable remote fails fast instead of prompting), and
  `run_git` globally gained `stdin=DEVNULL` so no git call can ever hang on
  a credential prompt. Offline mode lists the real subjects, proving the
  history flows end to end in the tests: 4 new (log lines newest-first from
  a real local repo, empty on an unfetchable URL, the API-stored changelog
  contains the real subjects, the fallback document). Design note:
  architecture/DOCUMENTATION_SUITE.md (updated in place). Engine 361
  passed, 1 skipped; web untouched.
- 2026-07-17 · Manual workspace push: the last stranded step in the
  edit-by-hand loop. A finished run's workspace could be browsed, edited,
  and committed from the run page — but the commit stayed local.
  `POST /v1/runs/{id}/push` now sends the run branch to its host through
  the same `push_branch` the pipeline publishes with: a GitLab repository
  authenticates with the run owner's encrypted connection, GitHub with the
  environment token, anything else pushes plainly — so an updated branch
  refreshes the run's existing pull request. Finished runs only (the same
  409 the write endpoints use), a scratch workspace's missing remote is a
  plain-language 400, and every push lands on the timeline as
  `branch.pushed` with who pressed the button. The git panel gained a
  Push branch button beside Commit. Proven against a real local bare
  origin in the tests: commit by hand, push by hand, the origin has the
  branch. Design note: architecture/WORKSPACE_PANELS.md (updated in
  place). Engine 357 passed, 1 skipped (3 new tests); web 19 passed.
- 2026-07-16 · Prompt snapshots: editing an agent prompt is now a visible
  decision instead of a silent behavior change. `tests/prompt_snapshots.json`
  records each of the nine prompts' SHA-256 (small, diff-friendly); the test
  fails on any drift — changed, added without a snapshot, or deleted — and
  names the file with the refresh command. The test module doubles as the
  refresher (`uv run python tests/test_prompt_snapshots.py`), so the format
  lives in one place; a second test pins the snapshot set to exactly the
  registry's prompt files. Verified the failure path for real: a one-newline
  edit failed the suite naming backend.md. Drift detection only — prompt
  *quality* stays the evaluation harness's job. Design note:
  architecture/PROMPT_SNAPSHOTS.md. Engine 354 passed, 1 skipped; web
  untouched.
- 2026-07-16 · Task-board agent tools (the Agent Tools workstream's last
  open item): engineers can now change the board they work from. `add_task`
  appends a newly discovered task (pending, next sequence, engineer roles
  only, board capped at 30) instead of the agent silently widening its own
  diff; `update_task_status` skips a pending task that turned out
  unnecessary — skipped-only by design (every other transition belongs to
  the runner and supervisor) and refused when unfinished work depends on
  the task, because a skipped dependency would deadlock the board. The
  supervisor learns about changes through the executor seam: the runner
  reloads the board after each task and returns an `ExecutionOutcome`
  (result + new tasks + skips) that the graph merges before scheduling —
  executors returning a plain string still mean "no board changes", so the
  existing semantics are untouched. Both tools audit to the timeline
  (`task.created`, `task.status_changed` with the reason), the engineer
  prompts teach the discipline, and the run page renders the new events in
  plain English. Design note: architecture/TASK_BOARD_TOOLS.md. Engine 352
  passed, 1 skipped (10 new tests across tools, supervisor merge, and the
  runner glue); web 18 passed.
- 2026-07-16 · Organization-aware sharing: the org claim now means something —
  repositories and agent runs created while an organization is active are
  visible, and writable, to whoever has that organization active (members
  are equal collaborators; roles are a later slice). The rule is stated
  exactly twice: `engine/db/visibility.py` (`can_access` for point lookups,
  `visible_clause` for lists — every route that checked `owner !=
  principal.user_id` on a repository or run now asks the helper), and the
  RLS policies, where the session pin gained `app.org_id` next to
  `app.user_id` and the org-shared tables' policies gained the matching
  clause (migration `0017_org_shared_rls`, `rls.py` still the living
  source). The engine never reads better-auth's member table: `setActive`
  already membership-checks the value the BFF signs, so `org` is trusted
  like `sub`. Conversations, provider keys, and integrations stay personal.
  Connecting an already-org-shared repository URL reuses the shared row
  instead of duplicating it. Design note:
  architecture/ORGANIZATION_SHARING.md. Engine 342 passed, 1 skipped (8 new
  tests attack both seams: raw SQL through pinned sessions and real requests
  carrying the claim); web 17 passed (panel copy).
- 2026-07-16 · Sign-in providers and the organization switcher (the last two
  Phase 1 identity items): the server decides which social buttons exist —
  `configuredProviders()` checks env credential pairs, the sign-in/sign-up
  pages pass the list to a client `SocialSignIn` block, and no credentials
  means the email form alone (social sign-in doubles as sign-up; better-auth
  creates the account on first OAuth round-trip). The settings page gained an
  Organizations panel — list, create, and switch the active organization or
  back to personal — and `signServiceToken` now takes the whole session, so
  every BFF-signed service JWT carries the active organization as its `org`
  claim (the engine's Principal already parses it). That claim is the seam
  org-aware RLS sharing builds on — that follow-up is now unblocked. Design
  note: architecture/SIGN_IN_AND_ORGANIZATIONS.md. Web 17 passed (2 new test
  files: the decoded token's claims, the provider-driven buttons); engine
  untouched.
- 2026-07-15 · Audit follow-ups (findings 2 and 3 closed the day they were
  raised): both process startups — the API lifespan and the arq worker — now
  call `warn_if_derived_key()`, which logs loudly when `ENGINE_ENCRYPTION_KEY`
  is unset and secrets at rest fall back to the key derived from
  `ENGINE_SERVICE_SECRET`; and the webhook receiver remembers queued
  `X-GitHub-Delivery` ids (bounded, in-process), so a GitHub redelivery is
  ignored instead of re-reviewing the same pull request. HMAC remains the
  security boundary — the dedupe is hygiene, and a replica restart at worst
  re-reviews once. Audit report updated in place. Engine 334 passed,
  1 skipped; web untouched.
- 2026-07-15 · Security-boundary audit (closing the planned Phase 7
  workstreams): every boundary the platform claims — service JWT, webhook
  HMAC, workspace path jail, clone/push URL hygiene, sandbox isolation,
  secrets at rest, row-level security, rate limiting, PR gates, CORS —
  walked and verified against the code, each with evidence and a verdict in
  security/SECURITY_AUDIT.md. One finding fixed in the same change: auth was
  a per-route convention (88 hand-written dependencies), so
  tests/test_route_auth_sweep.py now flattens the real route table and calls
  every endpoint unauthenticated — anything that fails to 401 fails the
  suite, making the boundary structural. Two findings logged as follow-ups:
  the ENGINE_ENCRYPTION_KEY dev-fallback deserves a loud production warning,
  and webhook redeliveries re-review the same PR. Engine 330 passed,
  1 skipped; web untouched.
- 2026-07-15 · Performance benchmarks: `engine/benchmark.py` measures the
  three hot paths through the real code, offline (`LLM_FAKE=1`, fake
  embeddings — provider latency measures them, not us). Indexing: a
  synthetic 120-module corpus is git-committed, registered, and pushed
  through `index_repository` (clone, tree-sitter chunking, embedding,
  Postgres), then re-indexed unchanged to price the incremental no-op.
  Retrieval: the golden questions repeated through hybrid `retrieve_chunks`
  for p50/p95 per-query latency. Run pipeline: one golden task through
  plan → approve → execute → review with the fake model — which still
  includes a real Docker sandbox pass, so the number is honest about what a
  run costs beyond the model. First baseline table (dev machine, dated) is
  recorded in the design note; benchmarks tidy their synthetic corpora out
  of the database afterwards. Deliberately a CLI, not pytest timing
  assertions (those flake on slow runners) — the suite keeps a smoke test
  that the harness runs at tiny sizes. Design note:
  architecture/BENCHMARKS.md. Engine 328 passed, 1 skipped; web untouched.
- 2026-07-15 · Kubernetes deploy: the platform is now something `helm install`
  can put on a cluster. Two production images — the engine
  (`infra/docker/engine.Dockerfile`: python-slim + uv, git and
  postgresql-client for worktrees and backups, non-root) serves as API, arq
  worker, and migration Job purely by command; the web app
  (`infra/docker/web.Dockerfile`) builds Next.js `standalone` output so the
  runtime stage carries only the built server. The Helm chart
  (`infra/helm/asep`) deploys web/engine/worker with liveness+readiness on
  `/healthz` (public, untraced, unratelimited — probes cost nothing), an
  `alembic upgrade head` Job as a pre-install/pre-upgrade hook so code never
  starts against an old schema, and one Secret mirroring `.env.example`
  consumed via `envFrom` (or an operator-managed `existingSecret`). The
  engine Service stays ClusterIP-only — ADR-0002's "browsers never reach the
  engine" boundary, now enforced by cluster networking; only the web Service
  can get an Ingress. Postgres/Redis/S3 are operator-provided, with the two
  hard-won dev requirements documented in values.yaml: NOSUPERUSER engine
  role and pgvector reachable by it. Verified: both images build; the engine
  container answers `/healthz` 200 and the web container serves (307 to
  sign-in — a probe pass); `helm lint` + `helm template` green locally and
  now a CI job. Boundaries logged: sandbox off in-cluster, placeholder
  resource limits until benchmarks, no NetworkPolicy/mTLS/autoscaling yet.
  Design note: architecture/KUBERNETES_DEPLOY.md. Web 13 passed; engine
  code untouched.
- 2026-07-14 · Row-level security (defense in depth behind the API's
  owner-scoping): Postgres now refuses to hand a pinned session another
  user's rows, even when the query has no WHERE clause at all. Policies live
  on the five ownership-carrying tables (`repositories`, `conversations`,
  `agent_runs`, `provider_keys`, `integration_connections`) with ENABLE +
  FORCE row level security (migration 0016; `engine/db/rls.py` is the living
  source the test suite applies, so the *entire* suite runs under FORCE RLS).
  Pinning is automatic: `get_session` peeks at the same bearer token auth
  verifies, and an `after_begin` hook re-applies the transaction-local
  `app.user_id` on every transaction — a mid-request commit cannot drop it,
  and nothing leaks into the connection pool. The hard-won lesson: superusers
  bypass RLS entirely, and the compose bootstrap user cannot be demoted — so
  the dev compose now bootstraps as `postgres` and creates `asep` as a plain
  NOSUPERUSER role (init script; CI mirrors it), with pgvector installed into
  `template1` because it is not a trusted extension. The dev volume was
  rebuilt through the day-old backup path — dump, `down -v`, restore — which
  exercised the disaster-recovery runbook for real and taught the restore two
  documented tolerances. Boundaries logged as follow-ups: unset context is
  trusted (deny-by-default needs a non-owner API role), child tables are
  guarded through parents, org-aware sharing waits on the org switcher.
  Design note: architecture/ROW_LEVEL_SECURITY.md. Engine 325 passed,
  1 skipped; web untouched.
- 2026-07-14 · Backups & disaster recovery: `engine/backup.py` drives the
  standard `pg_dump`/`pg_restore` as subprocesses — custom-format dumps written
  atomically (`.part`, renamed only after `pg_restore --list` proves the
  archive readable), the newest `BACKUP_RETENTION` kept, and pruning only ever
  running after a *successful* dump so a failure can never eat the good
  backups before it. `BACKUP_ENABLED=1` adds a nightly cron to the arq worker;
  the CLI (`python -m engine.backup create|verify|restore`) covers the rest,
  and restore always takes an explicit `--database-url` because a destructive
  command should never guess its target. The exit criterion is in the test
  suite: a row written before the dump is read back from a database restored
  *from* that dump, on every push — plus a narrow, documented tolerance for a
  newer client's session settings against an older server (PG18 → PG16), with
  anything else still failing the restore. Runbook a stressed human can follow:
  runbooks/DISASTER_RECOVERY.md; design note: architecture/BACKUPS_AND_RECOVERY.md.
  Boundary: the backup directory is a local disk — shipping dumps off-host is
  the logged Deploy-workstream follow-up. Engine 319 passed, 1 skipped; web
  untouched.
- 2026-07-13 · Rate limiting on the engine API (the oldest debt-register entry,
  parked for Phase 7 since Phase 0): `engine/ratelimit.py` puts a per-caller
  token bucket in front of the API — `RATE_LIMIT_BURST` tokens refilling at
  `RATE_LIMIT_PER_MINUTE/60` per second, so bursts pass and sustained floods
  get a 429 with a `Retry-After` header. Callers are keyed by the *verified*
  JWT subject (one user cannot starve another); missing/invalid tokens fall to
  a per-IP bucket, so an unauthenticated flood is contained without fabricated
  subjects minting fresh buckets. Off by default (`RATE_LIMIT_PER_MINUTE=0`),
  so dev and tests are unaffected; `/healthz` is never throttled; stale buckets
  are pruned. The middleware is pure ASGI (SSE-safe) and sits inside the
  tracing span, so 429s land in the request metrics for free. Boundary: the
  bucket is per replica — a Redis-backed shared window is the Deploy-workstream
  follow-up, and the debt register now says exactly that. Design note:
  architecture/RATE_LIMITING.md. Engine 312 passed, 1 skipped; web untouched.
- 2026-07-13 · Phase 7 opens — OpenTelemetry traces + metrics (ADR-0010's
  planned revisit): `engine/observability.py` holds the SDK switch —
  instrumentation goes through the OTel *API* unconditionally, so spans and
  metrics are no-ops until `OTEL_ENABLED=1` installs the SDK
  (`configure_telemetry()`, OTLP/HTTP export to
  `OTEL_EXPORTER_OTLP_ENDPOINT`; instrumented code carries no telemetry
  branches). A pure-ASGI middleware (SSE-safe, `/healthz` excluded) emits one
  server span per request named by its route template plus a request counter
  and duration histogram; every ModelRouter call gets an `llm.*` span (tier,
  model, tokens, cost — fake mode included, so traces exist offline); and
  `run.plan` / `run.execute` spans tie a whole agent run together for
  post-mortems. Tests inject in-memory exporters through the same seam and
  read real spans offline. No collector in compose — the engine exports;
  running the telemetry stack is the operator's side (Deploy workstream).
  Phase plan + design note: architecture/PRODUCTION_HARDENING.md; ADR-0010
  updated. Engine 306 passed, 1 skipped; web unchanged.
- 2026-07-13 · Workspace editor + git-commit panel: the run-page file browser
  became a light editor. Three new owner-scoped, jailed endpoints —
  `PUT /v1/runs/{id}/files/content` (replace a file), `GET …/git-status`
  (`git status --porcelain` → `{path, code}` list), and `POST …/commit`
  (`git add -A` + commit, returns the short sha). Writes are refused with a `409`
  unless the run is finished (`completed`/`failed`): while a run is queued /
  planning / executing / reviewing the agent loop owns the workspace, so a human
  write then would race it. The run page's viewer becomes a textarea with a Save
  button on a finished run, and a Working-tree panel lists changes and commits
  them. The commit stays local to the workspace — re-publishing it to the host is
  a later item. Design note: architecture/WORKSPACE_PANELS.md. Engine 300 passed,
  1 skipped; web 13 passed, build clean.
- 2026-07-13 · Workspace Panels open — a read-only file browser on the run page:
  a completed run's workspace persists on disk (only a rejected/recovered run
  deletes it), so two new owner-scoped endpoints read it live —
  `GET /v1/runs/{id}/files` (the workspace's files as a sorted, capped list of
  `{path, size}`, `.git` hidden) and `GET /v1/runs/{id}/files/content?path=…`
  (one file's text, size-capped, `truncated` flag). Every path goes through the
  same `resolve_inside` jail the agent tools use, so a `..`/absolute/symlink/UNC
  path is a `400` and can never read outside the workspace; a missing workspace
  is a graceful `404` like the diff. The run page gained a Files section — the
  file list beside a read-only viewer — next to the existing diff and timeline.
  The shared `_load_run_workspace` helper also de-duplicated the diff endpoint.
  Editing, git staging, and a terminal (the ADR-0008 arbitrary-shell boundary)
  are deliberately deferred. Design note: architecture/WORKSPACE_PANELS.md.
  Engine 294 passed, 1 skipped; web 13 passed, build clean.
- 2026-07-13 · Source hosts — GitLab merge requests: the run publish step is now
  host-aware. `engine/integrations/gitlab.py` recognizes `gitlab.com` URLs
  (`parse_gitlab_repo`, nested project paths) and opens a merge request via
  `POST /api/v4/projects/{path}/merge_requests` with a `PRIVATE-TOKEN` header,
  returning the MR's web URL; `INTEGRATIONS_DRY_RUN=1` returns a placeholder so
  the piece is testable offline. `gitlab` is a connection kind (`{token,
  base_url}`, default `https://gitlab.com`, encrypted at rest) but not an issue
  tracker. `push_branch` gained an optional credential — the default keeps its
  GitHub-env behavior byte-for-byte, and `_publish` passes an `("oauth2", token)`
  credential for a GitLab repo and opens the MR with the run owner's connection.
  A repo on neither host publishes the branch only, exactly as before, so the
  GitHub golden path is unchanged (all run-pipeline tests green). The settings
  page connects GitLab (token + optional base URL). Design note:
  architecture/SOURCE_HOSTS.md. Engine 288 passed, 1 skipped; web 13 passed,
  build clean.
- 2026-07-13 · Jira as a second issue tracker: the shared "an issue was created"
  contract (`IssueResult`) moved into the dispatcher (`engine/integrations/issues.py`),
  and a new Jira adapter (`engine/integrations/jira.py`) POSTs to Jira Cloud's
  `/rest/api/3/issue` with HTTP-Basic auth (email + API token) and an Atlassian
  Document Format description, returning the issue's browse URL and key.
  `INTEGRATIONS_DRY_RUN=1` returns a deterministic placeholder so the path runs
  offline. The same `POST …/work-items/{id}/push` endpoint now accepts `jira`,
  the settings page connects Jira (site URL, email, token, project key —
  encrypted at rest), and the planning board offers a push action per connected
  tracker. A differently-shaped API behind the unchanged dispatch is the proof
  the abstraction holds. Design note: architecture/EXTERNAL_INTEGRATIONS.md.
  Engine 283 passed, 1 skipped; web 13 passed, build clean.
- 2026-07-13 · Issue-tracker push (Linear) on the integrations foundation: a
  work item can now be pushed to Linear as an issue from the planning board.
  A new Linear adapter (`engine/integrations/linear.py`) calls the `issueCreate`
  GraphQL mutation and returns the issue's URL and human key (e.g. `ENG-42`);
  `INTEGRATIONS_DRY_RUN=1` returns a deterministic placeholder so the whole push
  path runs offline. A tracker-agnostic dispatch (`engine/integrations/issues.py`)
  maps a tracker kind to its adapter, so the push endpoint never names a specific
  tracker and Jira slots in as one more entry. Work items gained
  `external_issue_url` / `external_issue_key` (migration 0015, up/down/up
  verified); `POST …/work-items/{id}/push` creates the issue from the item's
  title and description, stores the link, and returns the updated item (404 when
  the tracker is not connected). The planning board shows the linked issue key
  and a push / re-push action; the settings page connects Linear (API key + team
  id, encrypted at rest). The Slack `test` endpoint stays Slack-only — a
  tracker's "test" would create a junk issue. Design note:
  architecture/EXTERNAL_INTEGRATIONS.md. Engine 279 passed, 1 skipped; web 13
  passed, build clean.
- 2026-07-12 · External integrations foundation + outbound Slack: a new
  `integration_connections` table (migration 0014, up/down/up verified) holds
  one encrypted connection per (user, kind), AES-GCM at rest like the provider
  keys — only the ciphertext and a non-secret label are stored. An adapter layer
  (`engine/integrations/`) does the outward work: `slack.post_message` posts to
  an incoming webhook, and `INTEGRATIONS_DRY_RUN=1` (tests, offline dev) makes
  every adapter skip the network and report success. When a run reaches a
  terminal state, `notify_run_outcome` runs beside the memory capture — it loads
  the owner's enabled Slack connection, posts the outcome (pull-request link or
  failure reason), and records an `integration.notified` timeline event; like
  capture it never breaks a run, and a run with no connection notifies nothing.
  The API (list / set / delete / test under `/v1/integrations`) and the
  Integrations section on `/settings` connect, test, and remove a Slack webhook;
  `IntegrationKind` names Jira/Linear/GitLab/Bitbucket too, but the API only
  accepts the active kinds (this slice: slack). Design note:
  architecture/EXTERNAL_INTEGRATIONS.md. Engine 272 passed, 1 skipped; web 13
  passed, build clean.
- 2026-07-12 · Phase 6 opens — documentation generation suite: a new
  Technical Writer agent role (read-only, planner tier;
  `engine/agents/prompts/technical_writer.md`) turns the repository index into a
  human-facing Markdown document. `engine/docs/generator.py` grounds the writer
  the way the Scrum Master is grounded — the repository's file map plus the code
  hybrid-retrieved for a kind-specific seed query, with recalled team memory
  riding along as context — and produces one of four kinds: `readme`,
  `api_reference`, `changelog`, or `architecture`. Documents persist in
  `generated_documents` (migration 0013, up/down/up verified), repository-scoped
  and durable; unlike a knowledge item they are written for people, so they are
  neither embedded nor fed back into agent context. The API (generate / list /
  delete under `/v1/repositories/{id}/documents`) and the `/docs` page (pick a
  kind, generate, read, delete) make it usable. Under `LLM_FAKE=1` the generator
  returns a deterministic document listing the repository's real files, so the
  whole path runs offline. Design note: architecture/DOCUMENTATION_SUITE.md.
  Engine 261 passed, 1 skipped; web 13 passed, build clean.
- 2026-07-12 · Identity & Keys — bring-your-own provider keys: each user can
  store an Anthropic / OpenAI / Gemini key, AES-GCM-encrypted at rest
  (`engine/security/crypto.py`; `ENGINE_ENCRYPTION_KEY`, dev fallback derived
  from the service secret) in the `provider_keys` table (migration 0012,
  up/down/up verified). The API (`/v1/provider-keys`) lists only provider +
  last four characters — the key never leaves the engine. Resolution order:
  the caller's key for the model's provider wins, the server's .env key is
  the fallback; the keys ride a context variable set at the entry points
  (chat, a run's planning and execution, roadmap generation), so the
  ModelRouter stays the single litellm gateway with no signature plumbing.
  The `/settings` page sets, replaces, and removes keys (masked to last
  four), linked from every screen. Design note: architecture/PROVIDER_KEYS.md.
  Engine 254 passed, 1 skipped; web 13 passed, build clean.
- 2026-07-12 · Agent Runtime — background worker (the last blocking runtime
  item): a new dispatch seam (`engine/jobs.py`) sends "plan this run" /
  "execute this run" either inline (the default — today's behavior, untouched)
  or onto a Redis queue for the arq worker process (`engine/worker.py`,
  `RUN_QUEUE=arq`). Both job functions are re-entrant: before running they
  reset an interrupted run the way startup recovery does, so the graceful
  shutdown story holds end to end — cancelling a run mid-task leaves the
  Postgres checkpoint intact (proven by a test that cancels mid-execution and
  asserts the run froze, not failed) and the re-delivered job finishes it. A
  dead queue degrades to inline with a warning, never parking a run; API
  startup recovery is gated to inline mode so it can't fight a healthy
  worker. Live arq round trip (enqueue → burst worker → plan → approve →
  execute → completed) runs against the dev Redis. Design note:
  architecture/BACKGROUND_WORKER.md. Engine 245 passed, 1 skipped.
- 2026-07-11 · Agent Runtime — run event bus (live timeline streaming): the
  runner pings a per-run Redis channel after every event commit
  (`engine/events/bus.py`), and `GET /v1/runs/{id}/events/stream` pushes each
  timeline entry over SSE the moment it lands — Postgres stays the record,
  Redis is only the doorbell, and a 2-second heartbeat covers a missing Redis
  entirely, so a lost ping costs latency, never an event. Streams resume from
  `Last-Event-ID` (or `?after=`), end with an `end` event at a terminal
  status, and stay open across the approval pause. The run page swapped its
  1.5-second event polling for one `EventSource` (each pushed event nudges a
  throttled task-board refresh) and falls back to polling if the stream is
  unreachable. Design note: architecture/RUN_EVENT_STREAMING.md. Engine 240
  passed, 1 skipped; web 13 passed.
- 2026-07-11 · Agent Runtime — run recovery (resume after restart): the
  `agent_tasks` board in Postgres already checkpoints every status change, so
  `engine/agents/recovery.py` closes the gap — at engine startup, runs frozen
  in `queued`/`planning` are re-planned from scratch (the half-made plan and
  workspace are discarded) and runs frozen in `executing`/`reviewing` resume
  from their board: done tasks keep their commits, the interrupted task
  repeats, and reviewing runs fall straight through to review. Every recovered
  run carries a `run.recovered` timeline event; runs awaiting approval and
  terminal runs are untouched. Gated by `RUN_RECOVERY_ENABLED` (on by default,
  off in tests, which call recovery directly). Design note:
  architecture/RUN_RECOVERY.md. Engine 234 passed, 1 skipped.
- 2026-07-11 · Grounded chat reads the team memory (Phase 5 complete, stretch
  item shipped): chat about a connected repository recalls the memories most
  relevant to the question into its system context next to the code excerpts,
  streams a `memory` SSE event naming them (the citations pattern), and the
  chat UI shows a "Remembered" list under the answer. Engine 229 passed; web
  13 passed.
- 2026-07-11 · Phase 5 core — Knowledge & Memory (both exit criteria met): the
  `knowledge_items` table (migration 0011, up/down/up verified) holds durable,
  repository-scoped memories — decisions, run outcomes, preferences, notes —
  each embedded and full-text indexed. Runs write their own history: a
  completed run captures its approved plan as a `decision` and its result as
  an `outcome` (a failed run captures why), and rejecting a plan at the
  approval gate records a `preference`; capture never breaks a run and is
  idempotent. Recall (`engine/knowledge/recall.py`, mirroring the Phase 2
  hybrid retrieval) feeds agent context: Product Manager planning injects a
  "Team memory" block with a `memory.recalled` timeline event, and Scrum
  Master roadmap generation recalls memories next to the repository file
  context. The knowledge API (list / search / add / delete under
  `/v1/repositories/{id}/knowledge`) and the `/knowledge` page (kind badges,
  source-run links, search, add-a-note form) make memory visible. Design
  note: architecture/KNOWLEDGE_AND_MEMORY.md. Engine 227 passed, 1 skipped;
  web 12 passed, build clean.
- 2026-07-10 · Scrum Master roadmap generation, estimation, and plan insights:
  `POST /v1/repositories/{id}/roadmap` hands a one-line goal (plus the indexed
  file paths as context) to the new Scrum Master role, whose validated JSON
  roadmap — items with milestones, kinds, relative estimates, priorities, a
  one-sentence rationale, and acyclic dependencies — is persisted to the backlog
  with position-based dependencies resolved to real work-item ids
  (`engine/agents/scrum_master.py`). Blocker detection and the next-item
  recommendation are deterministic (`engine/planning/insights.py`), served by
  `GET …/work-items/insights`, and shown as the Plan health section on the
  planning board. Design note: architecture/PLANNING_SUITE.md.
- 2026-07-10 · Durable work-items backlog and the planning board: the
  repository-scoped `work_items` table (migration 0010) holds planned work that
  outlives any single run — deleting the implementing run only nulls the link.
  Owner-scoped CRUD plus reorder under `/v1/repositories/{id}/work-items`
  validates that dependencies stay inside the repository. The `/planning` page
  lists the backlog in board order with drag-to-reorder, kind / priority /
  estimate / milestone badges, and inline status and estimate edits. Design
  note: architecture/PLANNING_SUITE.md.
- 2026-07-10 · Dependency vulnerability scan gates the pull request: a sibling of
  the secrets scanner (`engine/security/dependency_scanner.py`) reads only the
  *added* lines of the run's diff, extracts (package, version) pairs from
  requirements.txt, package.json, and package-lock.json manifests, and matches
  them against a curated, offline advisory list (known CVEs with a clear fixed
  version, matched by PEP 440 specifiers). The runner's `_dependency_gate` fails
  the run and records a `dependency.scan` timeline event when a known-vulnerable
  pin is introduced. Deterministic and network-free, so it runs in tests like the
  secrets gate. Design note: architecture/DEPENDENCY_SCANNING.md.
- 2026-07-09 · Webhook reviewer comments on real pull requests (Phase 3 exit
  criterion 2): `POST /v1/webhooks/github` authenticates GitHub deliveries by
  HMAC-SHA256 signature (constant-time, fail-closed on an unconfigured secret),
  queues a background review for `opened`/`reopened`/`synchronize` events, and
  returns 202 immediately. The task fetches the PR's unified diff, the
  diff-based Reviewer (`engine/agents/pr_reviewer.py`) returns strict-JSON
  findings, and one review comment is posted (`event: COMMENT`) — well inside
  five minutes. Design note: architecture/WEBHOOK_REVIEWER.md.
- 2026-07-09 · QA agent closes the self-correction loop: when the sandbox tests
  fail, `engine/agents/qa.py` hands the captured output to a new QA role (full
  engineer tool set, forbidden from gaming the tests), which fixes the code and
  commits; the runner re-runs the sandbox and repeats up to `QA_MAX_ATTEMPTS`
  (default 2) before failing the run. Each cycle is on the timeline — a
  `qa.attempt` event per fix and a `sandbox.run` event per re-run, both stamped
  with the attempt number. Design note: architecture/QA_AGENT.md.
- 2026-07-08 · Docker sandbox runs the tests before the pull request (Phase 3
  exit criterion 1): `engine/sandbox/runner.py` copies the workspace into a
  disposable container (2 GB / 2 CPUs / 256 processes, no host env vars),
  installs dependencies with the network on, disconnects the network, runs the
  detected test command time-boxed, and removes the container no matter what.
  The runner gates publication on the result: failed tests fail the run with a
  `sandbox.run` timeline event carrying the output tail; Docker-missing or
  no-test-setup skips are recorded, never silent. Live smoke test proved
  egress really is blocked during the test phase. Design note:
  architecture/SANDBOX_EXECUTION.md. Engine 132 passed, 1 skipped.
- 2026-07-08 · Phase 3 opens with the secrets gate (phase exit criterion met):
  `engine/security/secrets_scanner.py` scans only the lines a run *adds*
  (unified diff, high-confidence patterns for cloud keys, tokens, private
  keys, and labelled secret assignments; placeholders suppressed; findings
  stored redacted). The runner checks the diff after review approval and
  before the branch push — a hit fails the run with a `security.scan`
  timeline event and no pull request opens; a clean scan records the same
  event and proceeds. Design notes: architecture/EXECUTION_AND_QA.md (phase
  plan), architecture/SECRETS_SCANNING.md. Engine 116 passed, 1 skipped.
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
