# Product Requirements Document — ASEP

**Status:** Living document · **Owner:** Product · **Last updated:** 2026-07-02

## 1. Vision

ASEP is an AI-native software engineering platform that assists individuals and teams
across the *entire* software development lifecycle — not just code completion. It fields
a coordinated team of specialist AI agents (Product Manager, Backend Engineer, Frontend
Engineer, DevOps Engineer, Reviewer, and more) that understand a repository deeply, plan
work, implement it in reviewable increments, and keep documentation and tests current —
always with human approval gates at the moments that matter.

Long-term, ASEP evolves into an **AI Engineering Operating System**: idea → plan →
implementation → review → deployment → maintenance → continuous improvement.

## 2. Problem

| Pain | Today's reality |
|---|---|
| AI coding tools are editor-bound | Copilot/Cursor accelerate keystrokes, not the lifecycle (planning, review, docs, ops) |
| Autonomous agents are opaque | Devin-style agents run away with work; no structured team, weak human gates |
| Context is lost | Tools don't retain architecture decisions, conventions, or history between sessions |
| Teams duplicate coordination | Task breakdown, estimation, review, and docs remain manual overhead |

## 3. Personas

- **P1 — Solo builder / indie hacker.** Wants a whole "team" on demand: spec help,
  implementation, review, docs. Cost-sensitive; brings their own LLM keys.
- **P2 — Tech lead of a small team (2–10 devs).** Wants throughput without chaos:
  agent-generated PRs that respect conventions, automated review, planning support.
- **P3 — Engineering manager / platform owner.** Wants visibility (progress, blockers),
  governance (RBAC, audit, budgets), and safe rollout (self-host, SSO later).

## 4. Product pillars → brief goals

1. **AI Software Engineer** (G1) — plan, implement, refactor, fix, test, document.
2. **Repository Intelligence** (G2) — index, dependency/architecture graphs, debt & security detection.
3. **Multi-Agent Team** (G3) — PM, Architect, Backend, Frontend, DevOps, Security, QA, Writer, Reviewer, Research under structured task planning.
4. **Project Planning** (G4) — roadmaps, task breakdown, estimates, progress, blockers.
5. **Intelligent Coding** (G5) — features, bugs, refactors, APIs, schemas, migrations.
6. **Workflow Integrations** (G6) — Git(Hub/Lab/Bucket), Jira/Linear, Slack/Discord, Docker/K8s, CI/CD.
7. **Code Review** (G7) — PR review: bugs, breaking changes, perf, security, smells.
8. **Knowledge System** (G8) — persistent graph of repos, docs, decisions, PRs, tasks.
9. **AI Memory** (G9) — style, decisions, conversations, evolution, preferences.
10. **Production Deployment** (G10) — Docker/K8s, authn/z, logging, metrics, backups, DR.

## 5. v1 scope (Milestones 0–3)

**In scope**
- M0: monorepo foundation, auth skeleton, streaming chat spine (LiteLLM), dev infra, CI.
- M1: the multi-agent team v1 — feature request → PM spec + task breakdown → human
  approval → Backend/Frontend/DevOps agents implement in a git worktree → Reviewer
  critique loop → GitHub PR. Mission-control UI with live agent timeline.
- M2: repository intelligence — tree-sitter indexing (TS/JS, Python, Java/Kotlin),
  hybrid semantic + keyword search, dependency graphs, grounded chat with citations.
- M3: sandboxed execution (build/test in Docker), QA agent self-correction, PR-review
  agent via webhooks, secrets/dependency scanning.

**Explicit cutlines (not before M4+)**
- In-browser IDE (editor/terminal/debugger), Jira/Linear/Slack/Figma integrations,
  GitLab/Bitbucket, knowledge graph & long-term memory, K8s/production hardening,
  SSO/SAML, usage-based billing.

## 6. Core user journeys (v1)

1. **Chat about anything** (M0): sign in → chat with a model through the multi-provider
   gateway; conversations persist.
2. **Ship a feature with the agent team** (M1): connect GitHub repo → describe feature →
   review/approve the PM's plan → watch the team execute live → receive a PR → merge or
   request changes.
3. **Understand a codebase** (M2): connect repo → indexed automatically → ask "how does
   auth work here?" → grounded answer with file/line citations.
4. **Trust but verify** (M3): agent-run tests in a sandbox before the PR; automated
   review comments on every PR.

## 7. Success metrics

- **Activation:** first agent-team PR created within 30 minutes of signup.
- **Quality:** ≥ 60% of agent PRs merged without human code changes (target, measured from M1 eval set onward).
- **Trust:** 100% of code changes flow through human-approved plans and PRs; zero writes outside the workspace jail.
- **Retention:** weekly active runs per connected repo.
- **Cost:** per-run token budget respected; cost surfaced per run in the UI (M1).

## 8. Competitive positioning

| | Copilot / Cursor | Devin-class agents | **ASEP** |
|---|---|---|---|
| Center of gravity | Editor keystrokes | Single autonomous agent | SDLC team with human gates |
| Planning & PM artifacts | ✗ | Weak | First-class (specs, tasks, roadmaps) |
| Repo intelligence | Context window tricks | Ad-hoc | Persistent index + graphs (M2) |
| Review & QA | Basic | Self-review | Dedicated Reviewer/QA agents |
| Deployment | SaaS only | SaaS only | Self-host first, BYO LLM keys |

## 9. Non-functional requirements

- Self-hostable via Docker Compose (dev) and Kubernetes (M7).
- BYO LLM keys, multi-provider via LiteLLM; per-run cost caps.
- All agent file access jailed to per-run workspaces; no arbitrary shell before the M3 sandbox.
- Auditability: every agent action recorded (who/what/when) from M0's audit_logs onward.
- p95 chat first-token < 2s (excluding provider latency); index a 100k-LOC repo < 10 min (M2 target).

## 10. Open questions

- Pricing/packaging (self-host OSS core + paid cloud?) — decide before M6.
- Which agent roles get dedicated models vs shared tiers — revisit with M1 eval data.
- Multi-tenancy hardening timeline (row-level security) — before any hosted beta.
