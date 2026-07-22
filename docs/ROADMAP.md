# Roadmap

**Status:** Living document · **Last updated:** 2026-07-22
Effort is relative (small / medium / large). Every phase ships the full engineering
loop: architecture note → API spec → schema migration → UI/UX → implementation →
unit + integration tests → docs → performance/security pass (enforced by the PR
template). The task-level view lives in [BACKLOG.md](BACKLOG.md).

| Phase | Name | Effort | Delivers | Founding-brief goals served |
|---|---|---|---|---|
| **0** | **Foundation** *(complete)* | small | PRD, ADRs 0001–0010, roadmap, backlog; monorepo + turbo; compose dev env (pgvector, redis, minio); CI; better-auth skeleton; walking-skeleton chat through LiteLLM + minimal LangGraph; repo on GitHub | enables all |
| **1** | **Multi-Agent Engineering Team** *(core loop, runtime durability, BYO keys, social sign-in, and the organization switcher shipped)* | large | Product Manager / Backend / Frontend / DevOps / Reviewer agents under a Supervisor: feature request → spec + task breakdown → human approval → implementation in a per-run git worktree → review loop → GitHub PR. Mission-control UI (live timeline, task board, diff viewer, approval gates). Budget caps, encrypted BYO keys, evaluation seed (fixture repo + 3 golden tasks) | multi-agent collaboration; partial AI software engineer & project planning |
| **2** | **Repository Intelligence** *(blocking workstreams complete 2026-07-08; Java/Kotlin AST grammar deferred)* | medium | Indexing pipeline: tree-sitter parsing (TS/JS + Python first, then Java/Kotlin), AST-aware chunking, embeddings (LiteLLM route), hybrid vector+FTS retrieval with RRF, dependency/architecture graphs, grounded chat with citations; agents consume the index | repository intelligence; partial AI software engineer |
| **3** | **Execution & QA** *(complete 2026-07-10)* | medium | Docker sandbox (no-egress build/test runs), QA agent with self-correction loops, PR-review agent via GitHub webhooks, secrets detection + dependency scanning | code review; testing & security |
| **4** | **Planning Suite** *(complete 2026-07-10)* | medium | Roadmap generation, estimation, blocker detection, priority recommendations; Scrum Master agent; task manager UI | project planning |
| **5** | **Knowledge & Memory** *(complete 2026-07-11)* | medium | Knowledge graph (decisions, meeting notes, PR history, preferences); long-term team/repo memory feeding agent context | knowledge system; AI memory |
| **6** | **Workspace & Integrations** *(complete 2026-07-19 — documentation suite with git-history changelog and in-place editing; Slack / Linear / Jira / GitLab / Bitbucket integrations; run-workspace file browser + editor + git commit/push panel; and the sandboxed in-browser terminal)* | large | Editor / terminal / git panels; Jira, Linear, Slack; GitLab, Bitbucket; documentation generation suite (API docs, READMEs, changelogs, guides) | intelligent coding; workflow integrations |
| **7** | **Production Hardening** *(complete 2026-07-22 — observability + alerting with LLM cost metrics, Redis-shared rate limiting, off-host backups + PVC, row-level security with organization sharing and roles, the Kubernetes deploy with engine NetworkPolicy isolation, the DinD-capable in-cluster QA sandbox, a secret-gated real-model eval workflow, benchmarks, and the security audit; only certificate-manager mTLS and load-calibrated resource limits stay operator-gated)* | medium | K8s + Helm, OTel metrics/monitoring/alerting, backups + disaster recovery, RBAC depth + row-level security, security audit, performance benchmarks | production deployment |
| **8** | **Deliberate Reasoning** *(complete 2026-07-22)* | small | Every agent role reasons through an explicit chain of thought and *simulates* — predicts the outcome of its intended action — before acting, via the role prompts; the project's wrap-up quality pass | AI software engineer quality; deliberate, auditable decisions |

## Phase exit criteria

- **Phase 0 — Foundation:** compose healthy; `pnpm dev` boots web+engine; signed-in user
  gets a streamed LLM chat reply that persists; all lint/type/test suites green locally
  and in CI; repo pushed to GitHub with the foundation PR. ✅ *Met 2026-07-03.*
- **Phase 1 — Multi-Agent Engineering Team:** on the fixture repo, a feature request
  yields an approved plan, live-streamed execution, a Reviewer pass within one revision
  loop, and a coherent PR; 3/3 golden tasks pass the scripted evaluation.
- **Phase 2 — Repository Intelligence:** a 100k-LOC repo indexes < 10 min; "how does X
  work" answers cite real files/lines; retrieval evaluation beats a naive grep baseline
  on the golden question set. ✅ *Blocking indexing + retrieval workstreams met 2026-07-08;
  re-indexing is incremental and an HNSW index backs vector search.*
- **Phase 3 — Execution & QA** *(complete 2026-07-10)*: agent-modified code runs its tests
  in the sandbox before the PR; the review agent comments on a webhook'd PR within 5 min;
  the secrets scanner blocks a seeded leak. ✅ *All three met 2026-07-10; a dependency
  vulnerability scan gates the pull request alongside the secrets scanner.*
- **Phase 4 — Planning Suite** *(complete 2026-07-10)*: from a one-line goal the Scrum Master
  agent generates a milestone roadmap of estimated, dependency-linked work items saved to
  the backlog and shown on the task board; blocker detection flags an item waiting on an
  unfinished dependency and recommends the next unblocked, highest-value item to start.
  ✅ *Both met 2026-07-10.* Design note: [PLANNING_SUITE.md](architecture/PLANNING_SUITE.md).
- **Phase 5 — Knowledge & Memory:** a finished run leaves durable memory behind (the
  approved plan as a `decision`, the result as an `outcome`), searchable on the knowledge
  page after the run is gone; planning a new run recalls the most relevant memories into
  the planner's context — a stored preference demonstrably reaches the next run's
  planning prompt (the `memory.recalled` timeline event proves it). ✅ *Both met
  2026-07-11.* Design note: [KNOWLEDGE_AND_MEMORY.md](architecture/KNOWLEDGE_AND_MEMORY.md).
- **Phase 6 — Workspace & Integrations** *(in progress)*: the documentation
  generation suite is the first slice — from a connected, indexed repository the
  Technical Writer agent produces a README, API reference, changelog, or
  architecture overview grounded in the repository's real files, saved per
  repository and readable on the docs page. ✅ *Documentation slice met
  2026-07-12.* Design note: [DOCUMENTATION_SUITE.md](architecture/DOCUMENTATION_SUITE.md).
  The external-integrations foundation opened with outbound Slack notifications:
  a run reaching a terminal state posts its outcome to the owner's Slack webhook
  (encrypted at rest) and records an `integration.notified` timeline event; the
  whole path runs in dry-run mode for tests and offline dev. ✅ *Slack slice met
  2026-07-12.* The issue-tracker slice followed: a work item pushes to Linear
  (`issueCreate`) from the planning board, storing the issue link on the item,
  behind a tracker-agnostic dispatch. Jira followed as a differently-shaped
  second tracker (REST + HTTP-Basic auth) behind the same dispatch, proving the
  abstraction holds. ✅ *Linear + Jira slices met 2026-07-13.* Design note:
  [EXTERNAL_INTEGRATIONS.md](architecture/EXTERNAL_INTEGRATIONS.md).
  The source-host slice made the publish step host-aware: a run on a `gitlab.com`
  repository pushes its branch and opens a **merge request** with the owner's
  encrypted GitLab token, while the GitHub path is unchanged. ✅ *GitLab slice
  met 2026-07-13.* Design note: [SOURCE_HOSTS.md](architecture/SOURCE_HOSTS.md).
  The Workspace Panels workstream opened with a read-only file browser on the run
  page: a run's persisted workspace is listed and any file opened read-only,
  jailed by the same path guard the agents use, then became a light editor: on a
  *finished* run a file can be edited and the change committed from a git panel
  (editing an in-flight run is refused, so a human write never races the agent
  loop). ✅ *File-browser + editor/commit slices met 2026-07-13.* Design note:
  [WORKSPACE_PANELS.md](architecture/WORKSPACE_PANELS.md). The remaining slices
  then landed: a manual branch push from the workspace panel, Bitbucket as a
  second non-GitHub host behind the same dispatch, and the sandboxed in-browser
  terminal (a lazy `--network none` container, workspace copied not mounted,
  30-minute idle TTL) — closing the phase. ✅ *Phase 6 complete 2026-07-19.*
- **Phase 7 — Production Hardening** *(in progress)*: observability opened the
  phase, wiring the OTel SDK the way ADR-0010 planned — with telemetry enabled,
  one chat request produces a request span (route + status) and an LLM span
  (tier, model, tokens) plus a request-counter increment, proven offline by
  in-memory exporters in the test suite; disabled (the default) is a no-op.
  ✅ *Observability slice met 2026-07-13.* Rate limiting followed — a
  per-caller token bucket in front of the API (429 + `Retry-After`, off by
  default), retiring the oldest debt-register entry. ✅ *Rate-limiting slice met
  2026-07-13* ([RATE_LIMITING.md](architecture/RATE_LIMITING.md)). Backups &
  disaster recovery followed: verified nightly `pg_dump`s (arq cron, retention
  pruning), a restore CLI whose target is always explicit, and a recovery
  runbook — with the restore path proven in the test suite, which reads a row
  back out of a database restored from a real dump on every push. ✅
  *Backups/DR slice met 2026-07-14*
  ([BACKUPS_AND_RECOVERY.md](architecture/BACKUPS_AND_RECOVERY.md), runbook:
  [DISASTER_RECOVERY.md](runbooks/DISASTER_RECOVERY.md)). Row-level security
  followed: Postgres itself now refuses a pinned API session another user's
  rows — policies on the five ownership-carrying tables, sessions pinned
  automatically to the verified JWT subject, the whole test suite running
  under FORCE RLS, and the engine demoted to a non-superuser role (superusers
  bypass RLS — the slice's hard-won lesson). ✅ *Row-level-security slice met
  2026-07-14* ([ROW_LEVEL_SECURITY.md](architecture/ROW_LEVEL_SECURITY.md)).
  The Kubernetes deploy followed: production images for the engine (one image —
  API, worker, and migration Job by command) and the web app (Next.js
  standalone), and a Helm chart with `/healthz` probes, a pre-upgrade
  migration Job, one Secret mirroring `.env`, and the engine kept
  ClusterIP-only behind the BFF — images build and answer locally, and CI
  lints and renders the chart on every push. ✅ *Kubernetes-deploy slice met
  2026-07-15* ([KUBERNETES_DEPLOY.md](architecture/KUBERNETES_DEPLOY.md)).
  Benchmarks followed: `python -m engine.benchmark` measures the three hot
  paths offline (indexing throughput, hybrid-retrieval p50/p95, one golden
  task through the whole run pipeline with the fake model), and the first
  baseline table is recorded in the design note — future regressions are a
  number moving, not a feeling. ✅ *Benchmarks slice met 2026-07-15*
  ([BENCHMARKS.md](architecture/BENCHMARKS.md)). The security-boundary audit
  closed the planned workstreams: every claimed boundary (service JWT,
  webhook HMAC, path jail, clone-URL hygiene, sandbox isolation, secrets at
  rest, RLS, rate limiting, PR gates, CORS) verified against the code with a
  recorded verdict; one finding fixed inline — a sweep test now calls every
  route unauthenticated and fails the suite on anything that doesn't 401, so
  per-route auth is a structural guarantee, not a convention — and two
  findings logged. ✅ *Security-audit slice met 2026-07-15*
  ([SECURITY_AUDIT.md](security/SECURITY_AUDIT.md)). Organization-aware
  sharing extended row-level security: repositories and agent runs created
  under an active organization are visible to its members — the rule stated
  once for the route filters and once inside Postgres (`app.org_id`
  alongside `app.user_id`), with conversations and provider keys staying
  personal. ✅ *Organization-sharing slice met 2026-07-16*
  ([ORGANIZATION_SHARING.md](architecture/ORGANIZATION_SHARING.md)). The
  remaining hardening then shipped in a run of focused slices: organization
  members/invitations/roles with a destructive-action admin gate; the CI
  end-to-end smoke (which caught a latent alembic-commit bug); the Redis-shared
  rate-limit window; off-host backups to S3/MinIO and a backup PersistentVolume;
  a secret-gated real-model evaluation workflow; alerting rules with the LLM
  cost metric they watch, plus a validated OTel Collector config; engine
  network isolation via a NetworkPolicy; and the in-cluster QA sandbox via a
  Docker-in-Docker sidecar (proven against a real DinD daemon). ✅ *Phase 7
  complete 2026-07-22.* Only two items stay open, each needing infrastructure
  that cannot be stood up and verified from the code alone — certificate-manager
  **mutual TLS** and **load-calibrated resource limits** — tracked in
  [OPERATOR_HANDOFF.md](OPERATOR_HANDOFF.md).
- **Phase 8 — Deliberate Reasoning** *(complete 2026-07-22)*: every agent role
  now reasons before it acts. Each role prompt gained a short, uniform
  "think → simulate → act" directive — reason through the task as a chain of
  thought, then *simulate* (predict the outcome of the intended change, and what
  could break) before touching the workspace. Prompt-level by design: no extra
  LLM calls, no pipeline change; the reasoning rides in the model's own first
  turn and is captured by the prompt-snapshot contract. ✅ *Met 2026-07-22.*
  Design note: [DELIBERATE_REASONING.md](architecture/DELIBERATE_REASONING.md).

## Standing tracks (every phase)

- **Backlog hygiene:** `BACKLOG.md` re-prioritized at each phase boundary.
- **Tech debt:** debt register lives in BACKLOG §Debt; budgeted ~15% per phase.
- **Evaluations:** golden-task suites grow with each capability; regressions block merge.
- **Docs:** PRD/OVERVIEW/ADRs updated in the same PR as the change they describe.
