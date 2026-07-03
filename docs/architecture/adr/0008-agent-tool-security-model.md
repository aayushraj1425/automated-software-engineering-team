# ADR-0008: Agent tool security model

**Status:** Accepted · **Date:** 2026-07-02

## Context

Agents edit code. Uncontrolled, that means arbitrary file access, arbitrary command
execution, and secret exfiltration. Trust is the product's core promise: *"100% of code
changes flow through human-approved plans and PRs; zero writes outside the workspace
jail"* (PRD §7).

## Decision

Defense in depth, phased:

1. **Path jail (Phase 1):** every run gets a workspace `.workspaces/<run-id>/` (repo clone +
   branch). All fs tools (`list_dir`, `read_file`, `search`, `apply_patch`) resolve
   paths and reject anything outside the workspace root (symlink-resolved).
2. **No arbitrary shell before the sandbox (Phase 1):** tools are a closed allowlist; there
   is no `run_command` tool until Phase 3.
3. **Sandboxed execution (Phase 3):** builds/tests run in disposable Docker containers with
   CPU/memory/time limits and **no network egress** by default.
4. **Human gates:** plan approval before any edit; PR (never direct push to default
   branches) as the only merge path.
5. **Audit:** every tool call and state transition lands in `audit_logs`/`agent_events`
   with actor, run, and arguments.
6. **Secrets hygiene:** provider keys encrypted at rest (AES-GCM, master key from env);
   workspace tools refuse to read `.env*` and common credential paths; prompts never
   receive raw keys.
7. **Budgets:** per-run token/cost caps abort runaway loops (ADR-0006).

## Alternatives considered

- **Full VM/microVM isolation (Firecracker/gVisor) from day 1** — strongest isolation,
  heavy infra; planned as the Phase 7+ hardening path for hosted multi-tenancy.
- **Unrestricted shell with LLM self-policing** — how several agent products started;
  rejected outright, prompt injection makes it untenable.

## Consequences

- Some tasks (installing deps to verify builds) are impossible until Phase 3 — accepted;
  the Reviewer agent compensates partially in Phase 1.
- Path jail code becomes security-critical and gets dedicated tests (traversal,
  symlink escape, UNC paths on Windows).
