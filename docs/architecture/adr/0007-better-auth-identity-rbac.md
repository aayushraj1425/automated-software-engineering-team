# ADR-0007: better-auth for identity, sessions, orgs, and RBAC

**Status:** Accepted · **Date:** 2026-07-02

## Context

Requirements: OAuth sign-in (GitHub, Google, Microsoft), session management, and
role-based access control with organizations/teams — self-hosted, in our Postgres.

## Decision

- **better-auth** in apps/web owns identity: email+password (dev/local), GitHub OAuth
  first (developer product), Google/Microsoft enabled by env when configured, database
  sessions in Postgres, and the **organization plugin** for orgs/members/roles.
- better-auth's CLI migration (`pnpm --filter web auth:migrate`) owns identity tables
  (`user`, `session`, `account`, `organization`, `member`, `invitation`, …). Engine
  tables reference user/org ids as plain text columns, no cross-schema FKs (ADR-0002).
- The BFF asserts identity to the engine via the signed service JWT; the engine never
  reads session cookies.

## Alternatives considered

- **Auth.js (NextAuth v5)** — the incumbent with a huge provider list, but orgs/RBAC
  are DIY and v5 spent a long time in beta; we'd build the organization model ourselves.
- **Clerk / Auth0 / WorkOS** — fastest to ship and polished UIs, but SaaS lock-in,
  per-MAU pricing, and a conflict with self-host positioning.
- **Hand-rolled (lucia-style)** — full control, but auth is exactly where hand-rolling
  bites; not a differentiator worth owning.

## Consequences

- RBAC vocabulary (owner/admin/member) comes from the organization plugin; engine-side
  authorization checks use role claims carried in the service JWT (hardened in M7).
- Identity schema evolution is coupled to better-auth releases; pin versions and run
  `auth:migrate` as part of `pnpm db:migrate`.
- If better-auth stalls as a project, the migration path is Auth.js + a hand-built org
  layer; session/user tables are conventional enough to port.
