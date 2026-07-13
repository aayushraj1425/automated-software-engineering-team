# Roadmap

**Status:** Living document · **Last updated:** 2026-07-13
Effort is relative (small / medium / large). Every phase ships the full engineering
loop: architecture note → API spec → schema migration → UI/UX → implementation →
unit + integration tests → docs → performance/security pass (enforced by the PR
template). The task-level view lives in [BACKLOG.md](BACKLOG.md).

| Phase | Name | Effort | Delivers | Founding-brief goals served |
|---|---|---|---|---|
| **0** | **Foundation** *(complete)* | small | PRD, ADRs 0001–0010, roadmap, backlog; monorepo + turbo; compose dev env (pgvector, redis, minio); CI; better-auth skeleton; walking-skeleton chat through LiteLLM + minimal LangGraph; repo on GitHub | enables all |
| **1** | **Multi-Agent Engineering Team** *(core loop, runtime durability, and BYO keys shipped; GitHub OAuth sign-in and the organization switcher remain in the backlog)* | large | Product Manager / Backend / Frontend / DevOps / Reviewer agents under a Supervisor: feature request → spec + task breakdown → human approval → implementation in a per-run git worktree → review loop → GitHub PR. Mission-control UI (live timeline, task board, diff viewer, approval gates). Budget caps, encrypted BYO keys, evaluation seed (fixture repo + 3 golden tasks) | multi-agent collaboration; partial AI software engineer & project planning |
| **2** | **Repository Intelligence** *(blocking workstreams complete 2026-07-08; Java/Kotlin AST grammar deferred)* | medium | Indexing pipeline: tree-sitter parsing (TS/JS + Python first, then Java/Kotlin), AST-aware chunking, embeddings (LiteLLM route), hybrid vector+FTS retrieval with RRF, dependency/architecture graphs, grounded chat with citations; agents consume the index | repository intelligence; partial AI software engineer |
| **3** | **Execution & QA** *(complete 2026-07-10)* | medium | Docker sandbox (no-egress build/test runs), QA agent with self-correction loops, PR-review agent via GitHub webhooks, secrets detection + dependency scanning | code review; testing & security |
| **4** | **Planning Suite** *(complete 2026-07-10)* | medium | Roadmap generation, estimation, blocker detection, priority recommendations; Scrum Master agent; task manager UI | project planning |
| **5** | **Knowledge & Memory** *(complete 2026-07-11)* | medium | Knowledge graph (decisions, meeting notes, PR history, preferences); long-term team/repo memory feeding agent context | knowledge system; AI memory |
| **6** | **Workspace & Integrations** *(documentation suite, outbound Slack, Linear + Jira issue push, and GitLab merge requests shipped; editor/terminal/git panels and Bitbucket remain)* | large | Editor / terminal / git panels; Jira, Linear, Slack; GitLab, Bitbucket; documentation generation suite (API docs, READMEs, changelogs, guides) | intelligent coding; workflow integrations |
| **7** | **Production Hardening** | medium | K8s + Helm, OTel metrics/monitoring/alerting, backups + disaster recovery, RBAC depth + row-level security, security audit, performance benchmarks | production deployment |

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
  The editor/terminal/git panels and Bitbucket (the next host behind the same
  seam) remain.

## Standing tracks (every phase)

- **Backlog hygiene:** `BACKLOG.md` re-prioritized at each phase boundary.
- **Tech debt:** debt register lives in BACKLOG §Debt; budgeted ~15% per phase.
- **Evaluations:** golden-task suites grow with each capability; regressions block merge.
- **Docs:** PRD/OVERVIEW/ADRs updated in the same PR as the change they describe.
