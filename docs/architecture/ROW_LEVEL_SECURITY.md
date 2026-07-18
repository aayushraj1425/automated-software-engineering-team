# Row-Level Security

**Status:** Design accepted · **Phase:** 7 — Production Hardening · **Written:** 2026-07-14

## Why

Every engine API is owner-scoped: a query filters by the caller's user id, and
someone else's resource returns 404. That protection lives entirely in
hand-written `WHERE` clauses — one forgotten filter in one route and another
user's runs, conversations, or **encrypted provider keys** leak. Defense in
depth means the database itself must refuse to hand over rows that do not
belong to the caller, even when the query forgets to ask.

PostgreSQL row-level security does exactly that: a policy attached to the
table decides row-by-row what a session may see and write, no matter what SQL
the application sends.

## How it works

```mermaid
flowchart LR
    A[request with the\nBFF-signed JWT] --> B[require_service_auth\nverifies it — 401 if not]
    A --> C[get_session peeks at the\nsame token and pins the\nsession to its subject]
    C --> D[after_begin hook:\nSET app.user_id\nper transaction]
    D --> E[(Postgres policies:\nrow visible only when\nowner = app.user_id)]
    F[runner, webhooks,\nmigrations — no JWT] -->|session_scope sets\napp.service = 1| G[(explicit service\ncontext: full access)]
    H[no context at all —\na forgotten pin] --> X[(zero rows,\ndeny by default)]
```

- **Policies live on the five tables that carry ownership directly** —
  `repositories` (`owner_id`) and `conversations`, `agent_runs`,
  `provider_keys`, `integration_connections` (`user_id`). Each gets
  `ENABLE` **and** `FORCE` row level security: `FORCE` matters because the
  engine connects as the table owner, and owners bypass RLS without it.
- **A row is visible/writable when** `app.user_id` (a transaction-local GUC)
  equals the ownership column — **or when the GUC is unset**, which is the
  trusted internal context. The single source of truth for the policy SQL is
  `engine/db/rls.py`; the Alembic migration freezes a copy in time, and the
  test suite applies the living version.
- **Pinning is automatic, not per-route.** `get_session` peeks at the same
  bearer token `require_service_auth` verifies and stores the subject on the
  session; a SQLAlchemy `after_begin` hook applies
  `set_config('app.user_id', …, true)` at the start of **every** transaction.
  Transaction-local scope means nothing leaks back into the connection pool,
  and re-applying on every begin means a mid-request commit cannot drop the
  pin. Streaming endpoints pass the user to `session_scope(user_id=…)`
  explicitly.
- **Strictly additive.** Sessions that set no context — the agent runner,
  startup recovery, webhooks (verified by HMAC signature, not a user JWT),
  Alembic data migrations — behave exactly as before. The seam where bugs
  actually happen, hand-written route queries against a user-pinned session,
  is now guarded by Postgres.
- **The engine role must not be a superuser** — superusers bypass RLS no
  matter what, `FORCE` included (discovered the honest way: the policies
  passed every inspection and filtered nothing). Postgres also refuses to
  demote its bootstrap user, so the dev compose bootstraps as `postgres` and
  an init script creates `asep` as a plain `NOSUPERUSER CREATEDB` role owning
  its database (`infra/docker/postgres-init/`); CI mirrors this with a psql
  step. One knock-on: pgvector is not a *trusted* extension, so the init
  script installs it into `template1` as the superuser — every database
  created afterwards (dev, `asep_test`, backup-test scratch databases)
  inherits it, and the engine's `CREATE EXTENSION IF NOT EXISTS vector`
  becomes a no-op. The RLS test suite fails loudly with a rebuild hint if it
  ever finds itself running as a superuser.

## Exit criterion

With the policies applied (the whole test suite runs under `FORCE ROW LEVEL
SECURITY`), a session pinned to user B — issuing raw SQL with **no `WHERE`
filter at all** — reads only B's rows, updates zero rows of A's even when
targeting them by primary key, and gets a policy violation when inserting a
row that claims to belong to A. And the full existing suite stays green,
proving no code path silently depended on cross-user reads.

## Deny by default *(added 2026-07-17)*

The original slice trusted an *unset* context: a session that never pinned
saw everything. That kept internal paths working but meant a forgotten pin
was a silent leak. The policies now require an explicit assertion:

- **API sessions** pin `app.user_id` (+ `app.org_id`) as before.
- **Internal paths** — the runner, webhooks, workers, backups — go through
  `session_scope()`, which now sets `app.service='1'`: the explicit service
  context. The alembic connection asserts it too, so data migrations work.
- **A session with neither** — a raw connection outside the helpers, the
  exact shape of a forgotten pin — reads zero rows, updates zero rows even
  by primary key, and cannot insert. Forgetting context is loud, not a leak.

`pg_restore` keeps working because policies are recreated *after* the data
loads (post-data section) — proven by the restore-from-a-real-dump test.

## Honest boundaries

- **The service flag guards against our own bugs, not a database attacker.**
  Anyone who can already run arbitrary SQL on the connection can also run
  `set_config('app.service','1',…)`. True privilege separation needs a
  separate, non-owner database role for the API with no policy escape hatch
  — that remains on the backlog as its own slice.
- **Child tables are guarded through their parents.** `messages`,
  `agent_tasks`, `agent_events`, `code_chunks`, `work_items` carry no
  ownership column; the API reaches them only after an owner check on the
  parent. Subquery policies (`EXISTS (SELECT 1 FROM agent_runs …)`) can pin
  them down too, at a per-row planning cost — a follow-up, not this slice.
- **Organization-aware sharing shipped 2026-07-16** as its own slice on top
  of these policies: repositories and agent runs additionally open to
  sessions whose `app.org_id` (the JWT's membership-checked active
  organization) matches the row's `org_id`. Design note:
  [ORGANIZATION_SHARING.md](ORGANIZATION_SHARING.md).
