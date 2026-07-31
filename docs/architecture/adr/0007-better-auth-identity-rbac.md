# ADR-0007: better-auth for identity, sessions, orgs, and RBAC

**Status:** Accepted · **Date:** 2026-07-02

## Context

We need OAuth sign-in (GitHub, Google, Microsoft), session management, and
role-based access control with organizations and teams — all self-hosted, in our
own Postgres.

## Decision

- **better-auth, in apps/web, owns identity.** It handles email-and-password
  sign-in for local development, GitHub OAuth first (this is a developer product),
  and Google and Microsoft when their credentials are configured. Sessions live in
  Postgres, and the organization plugin provides organizations, members, and
  roles.
- **better-auth owns the identity tables.** Its CLI migration
  (`pnpm --filter web auth:migrate`) manages `user`, `session`, `account`,
  `organization`, `member`, `invitation`, and the rest. Engine tables reference
  user and organization ids as plain text columns, with no cross-schema foreign
  keys (ADR-0002).
- The BFF asserts identity to the engine through the signed service JWT; the
  engine never reads session cookies.

## Alternatives considered

- **Auth.js (NextAuth v5)** is the incumbent with a huge list of providers, but
  organizations and RBAC are do-it-yourself, and v5 spent a long time in beta. We
  would be building the organization model ourselves.
- **Clerk, Auth0, or WorkOS** are the fastest way to ship, with polished UIs, but
  they mean SaaS lock-in, per-monthly-active-user pricing, and a conflict with our
  self-host positioning.
- **Rolling our own** (in the style of Lucia) would give full control, but auth is
  exactly the place where hand-rolling comes back to bite you, and it is not a
  differentiator worth owning.

## Consequences

- The RBAC vocabulary (owner, admin, member) comes from the organization plugin,
  and engine-side authorization checks read the role claims carried in the service
  JWT (hardened in Phase 7).
- The identity schema evolves with better-auth's releases, so we pin versions and
  run `auth:migrate` as part of `pnpm db:migrate`.
- If better-auth ever stalls as a project, the way out is Auth.js plus a
  hand-built organization layer — the session and user tables are conventional
  enough to port.
