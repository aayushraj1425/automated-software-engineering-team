-- The engine must not connect as a superuser: superusers bypass row-level
-- security no matter what (docs/architecture/ROW_LEVEL_SECURITY.md), and
-- Postgres refuses to demote the bootstrap user itself. So the bootstrap
-- user is `postgres`, and `asep` — the role everything connects as — is
-- created here as a plain role that owns its database. CREATEDB stays
-- because the test suite creates its own databases.
CREATE ROLE asep LOGIN PASSWORD 'asep' NOSUPERUSER CREATEDB;

-- Privilege separation (ROW_LEVEL_SECURITY.md): user-pinned API sessions
-- connect as this non-owner role (DATABASE_URL_API). It cannot drop or
-- disable a policy, and the policies' service clause checks the *role*, so
-- setting the app.service GUC gains it nothing. DML grants come from the
-- migrations; existing volumes create it once with this same line.
CREATE ROLE asep_api LOGIN PASSWORD 'asep_api' NOSUPERUSER;

-- pgvector is not a trusted extension (installing it needs superuser), so
-- install it into template1: every database created afterwards — asep here,
-- asep_test and scratch databases at test time — inherits it, and the
-- engine's `CREATE EXTENSION IF NOT EXISTS vector` becomes a no-op.
\connect template1
CREATE EXTENSION IF NOT EXISTS vector;

\connect postgres
CREATE DATABASE asep OWNER asep;

-- Runs on fresh volumes only; existing checkouts rebuild the volume once
-- (dump → down -v → up → restore; see the Gotchas section in CLAUDE.md).
