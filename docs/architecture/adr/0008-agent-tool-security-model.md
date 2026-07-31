# ADR-0008: Agent tool security model

**Status:** Accepted · **Date:** 2026-07-02

## Context

Agents edit code, and left uncontrolled that means arbitrary file access,
arbitrary command execution, and secret exfiltration. Trust is the core promise of
the product: *"100% of code changes flow through human-approved plans and PRs;
zero writes outside the workspace jail"* (PRD §7). The security model has to make
that promise true.

## Decision

Defense in depth, introduced in phases:

1. **A path jail.** Every run gets a workspace at `.workspaces/<run-id>/` — a repo
   clone on its own branch. Every filesystem tool (`list_dir`, `read_file`,
   `search`, `apply_patch`) resolves paths and rejects anything outside the
   workspace root, symlinks included.
2. **No arbitrary shell before the sandbox.** Tools are a closed allowlist; there
   is no `run_command` tool until the sandbox exists in Phase 3.
3. **Sandboxed execution.** Builds and tests run in disposable Docker containers
   with CPU, memory, and time limits, and no network egress by default.
4. **Human gates.** A plan is approved before any edit happens, and a pull request
   — never a direct push to a default branch — is the only path to merge.
5. **An audit trail.** Every tool call and state transition lands in `audit_logs`
   and `agent_events`, with the actor, the run, and the arguments.
6. **Secrets hygiene.** Provider keys are encrypted at rest (AES-GCM, master key
   from the environment); workspace tools refuse to read `.env*` and the common
   credential paths; and raw keys never reach a prompt.
7. **Budgets.** Per-run token and cost caps stop a runaway loop (ADR-0006).

## Alternatives considered

- **Full VM or microVM isolation from day one** (Firecracker, gVisor) gives the
  strongest isolation but demands heavy infrastructure. We plan it as the Phase 7+
  hardening path for hosted multi-tenancy rather than paying for it up front.
- **An unrestricted shell with the LLM policing itself** is how several agent
  products started. We reject it outright — prompt injection makes it untenable.

## Consequences

- Some tasks, such as installing dependencies to verify a build, are simply
  impossible until the Phase 3 sandbox arrives. We accept that; the Reviewer agent
  makes up for part of it in the meantime.
- The path jail becomes security-critical code, so it gets dedicated tests —
  traversal, symlink escape, and UNC paths on Windows.
