# Roadmap

**Status:** Living document · **Last updated:** 2026-07-03
Sizes are relative (S/M/L). Every phase ships the full engineering loop:
architecture note → API spec → schema migration → UI/UX → implementation → unit +
integration tests → docs → performance/security pass (enforced by the PR template).
The task-level view lives in [BACKLOG.md](BACKLOG.md).

| Phase | Name | Size | Delivers | Brief goals |
|---|---|---|---|---|
| **0** | **Foundation** *(complete)* | S | PRD, ADRs 0001–0010, roadmap, backlog; monorepo + turbo; compose dev env (pgvector, redis, minio); CI; better-auth skeleton; walking-skeleton chat through LiteLLM + minimal LangGraph; repo on GitHub | enables all |
| **1** | **Multi-Agent Engineering Team** *(next)* | L | Product Manager / Backend / Frontend / DevOps / Reviewer agents under a Supervisor: feature request → spec + task breakdown → human approval → implementation in a per-run git worktree → review loop → GitHub PR. Mission-control UI (live timeline, task board, diff viewer, approval gates). Budget caps, encrypted BYO keys, evaluation seed (fixture repo + 3 golden tasks) | G3; G1, G4 partial |
| **2** | **Repository Intelligence** | M | Indexing pipeline: tree-sitter parsing (TS/JS + Python first, then Java/Kotlin), AST-aware chunking, embeddings (LiteLLM route), hybrid vector+FTS retrieval with RRF, dependency/architecture graphs, grounded chat with citations; agents consume the index | G2; G1 partial |
| **3** | **Execution & QA** | M | Docker sandbox (no-egress build/test runs), QA agent with self-correction loops, PR-review agent via GitHub webhooks, secrets detection + dependency scanning | G7; testing + security |
| **4** | **Planning Suite** | M | Roadmap generation, estimation, blocker detection, priority recommendations; Scrum Master agent; task manager UI | G4 |
| **5** | **Knowledge & Memory** | M | Knowledge graph (decisions, meeting notes, PR history, preferences); long-term team/repo memory feeding agent context | G8, G9 |
| **6** | **Workspace & Integrations** | L | Editor / terminal / git panels; Jira, Linear, Slack; GitLab, Bitbucket; documentation generation suite (API docs, READMEs, changelogs, guides) | G5, G6 |
| **7** | **Production Hardening** | M | K8s + Helm, OTel metrics/monitoring/alerting, backups + disaster recovery, RBAC depth + row-level security, security audit, performance benchmarks | G10 |

## Phase exit criteria

- **Phase 0 — Foundation:** compose healthy; `pnpm dev` boots web+engine; signed-in user
  gets a streamed LLM chat reply that persists; all lint/type/test suites green locally
  and in CI; repo pushed to GitHub with the foundation PR. ✅ *Met 2026-07-03.*
- **Phase 1 — Multi-Agent Engineering Team:** on the fixture repo, a feature request
  yields an approved plan, live-streamed execution, a Reviewer pass within one revision
  loop, and a coherent PR; 3/3 golden tasks pass the scripted evaluation.
- **Phase 2 — Repository Intelligence:** a 100k-LOC repo indexes < 10 min; "how does X
  work" answers cite real files/lines; retrieval evaluation beats a naive grep baseline
  on the golden question set.
- **Phase 3 — Execution & QA:** agent-modified code runs its tests in the sandbox before
  the PR; review agent comments on a webhook'd PR within 5 min; secrets scanner blocks a
  seeded leak.

## Standing tracks (every phase)

- **Backlog hygiene:** `BACKLOG.md` re-prioritized at each phase boundary.
- **Tech debt:** debt register lives in BACKLOG §Debt; budgeted ~15% per phase.
- **Evaluations:** golden-task suites grow with each capability; regressions block merge.
- **Docs:** PRD/OVERVIEW/ADRs updated in the same PR as the change they describe.
