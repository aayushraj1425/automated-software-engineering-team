# Architecture notes

Every feature in ASEP has a design note here: what it does, why it was built that
way, and what was deliberately left out. Notes are written *before* the code, so
they capture intent rather than a description of the result.

New to the system? Read [`../architecture.md`](../architecture.md) first — it's the
narrative overview. This folder is the detailed reference behind it, grouped below
by area. The cross-cutting decisions with their rejected alternatives are in
[`adr/`](adr).

> Notes are grouped into subfolders by area (below); `OVERVIEW.md` and this index
> stay at the top. Use the index as the map — it's the fastest way to find the
> note you want.

## Start here

- [OVERVIEW.md](OVERVIEW.md) — the system's containers, flows, and data ownership (diagrams).

## The agent runtime and run pipeline

- [AGENT_RUNTIME.md](agents/AGENT_RUNTIME.md) — the run/task/event domain model and the pipeline lifecycle.
- [BACKGROUND_WORKER.md](agents/BACKGROUND_WORKER.md) — running runs on the arq queue vs. inline.
- [RUN_RECOVERY.md](agents/RUN_RECOVERY.md) — resuming an interrupted run from the task board.
- [RUN_EVENT_STREAMING.md](agents/RUN_EVENT_STREAMING.md) — "Postgres is the record, Redis is the doorbell."
- [DELIBERATE_REASONING.md](agents/DELIBERATE_REASONING.md) — the "think → simulate → act" prompt directive.
- [AGENT_REASONING_TIMELINE.md](agents/AGENT_REASONING_TIMELINE.md) — surfacing an agent's rationale on the timeline.
- [PLAN_EDITING.md](agents/PLAN_EDITING.md) — editing a plan at the approval gate.
- [PROMPT_SNAPSHOTS.md](agents/PROMPT_SNAPSHOTS.md) — the checked-in prompt hashes that fail the suite on drift.

## Agent tools

- [APPLY_PATCH_TOOL.md](agents/APPLY_PATCH_TOOL.md) — unified-diff edits via `git apply`.
- [RIPGREP_SEARCH.md](agents/RIPGREP_SEARCH.md) — the ripgrep-backed file search, with a pure-Python fallback.
- [AGENT_CODE_SEARCH.md](agents/AGENT_CODE_SEARCH.md) — the index-backed `search_code` tool.
- [TASK_BOARD_TOOLS.md](agents/TASK_BOARD_TOOLS.md) — how agents add or skip tasks mid-run.
- [PULL_REQUEST_BODY.md](agents/PULL_REQUEST_BODY.md) — the Definition-of-Done checklist in generated PRs.
- [SOURCE_HOSTS.md](agents/SOURCE_HOSTS.md) — host-aware publishing to GitHub, GitLab, and Bitbucket.

## Repository intelligence

- [REPOSITORY_INTELLIGENCE.md](repository-intelligence/REPOSITORY_INTELLIGENCE.md) — the indexing and retrieval overview.
- [AST_CHUNKING.md](repository-intelligence/AST_CHUNKING.md) — tree-sitter, AST-aware chunking.
- [INCREMENTAL_INDEXING.md](repository-intelligence/INCREMENTAL_INDEXING.md) — re-indexing only changed files; the HNSW index.
- [HYBRID_RETRIEVAL.md](repository-intelligence/HYBRID_RETRIEVAL.md) — vector + full-text search fused with reciprocal-rank fusion.
- [GROUNDED_CHAT.md](repository-intelligence/GROUNDED_CHAT.md) — answers that cite real files and lines.
- [DEPENDENCY_GRAPH.md](repository-intelligence/DEPENDENCY_GRAPH.md) — the import/architecture graph.
- [REPOSITORY_INDEX_FRESHNESS.md](repository-intelligence/REPOSITORY_INDEX_FRESHNESS.md) — showing when a repo was last indexed.
- [INDEXING_ERROR_SURFACING.md](repository-intelligence/INDEXING_ERROR_SURFACING.md) — surfacing why an index failed.

## Execution, QA, and security scanning

- [EXECUTION_AND_QA.md](execution-qa/EXECUTION_AND_QA.md) — the Phase 3 execution and QA overview.
- [SANDBOX_EXECUTION.md](execution-qa/SANDBOX_EXECUTION.md) — the network-isolated Docker test runner.
- [QA_AGENT.md](execution-qa/QA_AGENT.md) — running tests and the fix-and-retry loop.
- [SECRETS_SCANNING.md](execution-qa/SECRETS_SCANNING.md) — blocking a leaked secret before the PR.
- [DEPENDENCY_SCANNING.md](execution-qa/DEPENDENCY_SCANNING.md) — flagging vulnerable dependency changes.
- [WEBHOOK_REVIEWER.md](execution-qa/WEBHOOK_REVIEWER.md) — the GitHub-webhook pull-request review agent.

## Chat and conversations

- [CHAT_MESSAGE_RENDERING.md](chat/CHAT_MESSAGE_RENDERING.md) — Markdown replies with syntax-highlighted, copyable code blocks.
- [CONVERSATION_MANAGEMENT.md](chat/CONVERSATION_MANAGEMENT.md) — rename and delete conversations.
- [CONVERSATION_SEARCH.md](chat/CONVERSATION_SEARCH.md) — searching by title or message text.
- [CONVERSATION_EXPORT.md](chat/CONVERSATION_EXPORT.md) — exporting a conversation as Markdown.
- [CONVERSATION_TIMESTAMPS.md](chat/CONVERSATION_TIMESTAMPS.md) — the "last active" timestamp.

## Runs UI

- [AGENT_TIMELINE_LEGIBILITY.md](runs-ui/AGENT_TIMELINE_LEGIBILITY.md) — per-agent colours, thinking cards, expandable actions, per-file diffs.
- [RUN_REPORT.md](runs-ui/RUN_REPORT.md) — the shareable run report.
- [RUN_STATISTICS.md](runs-ui/RUN_STATISTICS.md) — the runs success-rate and spend summary.
- [RUN_SEARCH.md](runs-ui/RUN_SEARCH.md) — searching runs by request text.
- [RUN_RERUN.md](runs-ui/RUN_RERUN.md) — starting a fresh run from an existing one.
- [RUN_HISTORY_RETENTION.md](runs-ui/RUN_HISTORY_RETENTION.md) — deleting runs; surviving a repo disconnect.
- [RUN_TIMESTAMPS.md](runs-ui/RUN_TIMESTAMPS.md) — relative timestamps on the runs list.
- [TIMELINE_AGENT_FILTER.md](runs-ui/TIMELINE_AGENT_FILTER.md) — filtering the timeline to one agent.
- [WORKSPACE_PANELS.md](runs-ui/WORKSPACE_PANELS.md) — the file browser, editor, and git panel on a run.
- [IN_BROWSER_TERMINAL.md](runs-ui/IN_BROWSER_TERMINAL.md) — the sandboxed command console.

## Planning, knowledge, and documentation

- [PLANNING_SUITE.md](planning-knowledge/PLANNING_SUITE.md) — the Scrum Master agent and the planning backlog.
- [KNOWLEDGE_AND_MEMORY.md](planning-knowledge/KNOWLEDGE_AND_MEMORY.md) — long-term memory: store, recall, capture.
- [DOCUMENTATION_SUITE.md](planning-knowledge/DOCUMENTATION_SUITE.md) — the Technical Writer agent and generated docs.

## Identity, keys, and integrations

- [SIGN_IN_AND_ORGANIZATIONS.md](identity-integrations/SIGN_IN_AND_ORGANIZATIONS.md) — sign-in providers and the org switcher.
- [PROVIDER_KEYS.md](identity-integrations/PROVIDER_KEYS.md) — encrypted bring-your-own model keys.
- [ORGANIZATION_SHARING.md](identity-integrations/ORGANIZATION_SHARING.md) — sharing repositories and runs within an org.
- [ORGANIZATION_ROLES.md](identity-integrations/ORGANIZATION_ROLES.md) — members, invitations, and the admin gate.
- [BFF_PROXY.md](identity-integrations/BFF_PROXY.md) — the single web→engine proxy helper.
- [EXTERNAL_INTEGRATIONS.md](identity-integrations/EXTERNAL_INTEGRATIONS.md) — the encrypted connection store; Slack, Linear, Jira.

## Security and data protection

- [ROW_LEVEL_SECURITY.md](security/ROW_LEVEL_SECURITY.md) — Postgres refusing another user's rows.
- [AUDIT_LOG.md](security/AUDIT_LOG.md) — the actor/action audit trail; the tool-call mirror.

## Production hardening and operations

- [PRODUCTION_HARDENING.md](operations/PRODUCTION_HARDENING.md) — the Phase 7 plan.
- [KUBERNETES_DEPLOY.md](operations/KUBERNETES_DEPLOY.md) — production images, the Helm chart, network isolation.
- [RATE_LIMITING.md](operations/RATE_LIMITING.md) — the per-caller token bucket, shared across replicas via Redis.
- [BACKUPS_AND_RECOVERY.md](operations/BACKUPS_AND_RECOVERY.md) — verified dumps, off-host shipping, restore.
- [ALERTING.md](operations/ALERTING.md) — the Prometheus rules and the LLM cost metric.
- [BENCHMARKS.md](operations/BENCHMARKS.md) — the offline performance baselines.
- [CI_END_TO_END_SMOKE.md](operations/CI_END_TO_END_SMOKE.md) — the Playwright smoke against the compose stack.

## Decision records

The [`adr/`](adr) folder holds the ten Architecture Decision Records — the
choices that shaped everything above, each with the alternatives that were
rejected and why. Read these when you want to understand *why the foundations are
the way they are*, not just how a feature works.
