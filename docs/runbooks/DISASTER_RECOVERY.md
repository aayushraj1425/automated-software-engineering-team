# Runbook — Restoring the Database from a Backup

**When to use this:** the Postgres database is lost, corrupted, or was
migrated somewhere it should not have been, and you need to get back to the
most recent nightly backup. Expect to lose whatever happened after that
backup was taken (nightly dumps = up to a day).

**Time needed:** about 10 minutes.
Design background: [BACKUPS_AND_RECOVERY.md](../architecture/BACKUPS_AND_RECOVERY.md).

```mermaid
flowchart LR
    A[stop the engine\nand the worker] --> B[pick the newest dump\nand verify it]
    B --> C[create a fresh\nempty database]
    C --> D[restore the dump\ninto it]
    D --> E[check the schema\nand the data]
    E --> F[restart and\nclick around]
```

## Before you ever need this page

- **The encryption key lives apart from the backups.** Provider keys and
  integration configs inside a dump are AES-GCM encrypted; without the
  `ENGINE_ENCRYPTION_KEY` from `.env`, a restored database cannot decrypt
  them. Keep a copy of that key somewhere that is not the backup disk.
- **Backups only exist if they are switched on** (`BACKUP_ENABLED=1` with the
  arq worker running), or taken by hand:

  ```sh
  cd apps/engine
  uv run python -m engine.backup create
  ```

- The dumps land in `BACKUP_DIR` (default `.backups/`), named like
  `asep-20260714T030000Z.dump`; the newest `BACKUP_RETENTION` are kept.

## The restore, step by step

All commands run from `apps/engine`. The connection values below are the dev
defaults (`asep`/`asep` on `localhost:5433`) — substitute production values.

**1. Stop writes.** Stop the engine API and the arq worker so nothing writes
to the database mid-restore.

**2. Pick a dump and prove it is readable** (never point a restore at a file
you have not verified):

```sh
uv run python -m engine.backup verify .backups/asep-20260714T030000Z.dump
# → ok: 142 archive entries
```

**3. Create a fresh, empty database** to restore into. Restoring next to the
broken one (instead of over it) means you can compare, and abort, at any point:

```sh
psql "postgresql://asep:asep@localhost:5433/postgres" -c "CREATE DATABASE asep_restored"
```

**4. Restore the dump into it** (the target is always explicit — restoring is
destructive, so the command never guesses):

```sh
uv run python -m engine.backup restore .backups/asep-20260714T030000Z.dump \
  --database-url "postgresql+psycopg://asep:asep@localhost:5433/asep_restored"
```

**5. Check what came back.** The schema should be at a known Alembic
revision, and the data should look like data:

```sh
psql "postgresql://asep:asep@localhost:5433/asep_restored" \
  -c "SELECT version_num FROM alembic_version" \
  -c "SELECT count(*) FROM runs"
```

If the Alembic revision is older than the code expects, run
`uv run alembic upgrade head` against the restored database *after* pointing
`DATABASE_URL` at it (next step) — never before checking what you have.

**6. Switch over.** Point `DATABASE_URL` in the root `.env` at the restored
database (or rename the databases so the restored one takes the old name),
start the engine and worker, sign in, and open a run's timeline. If the
identity tables restored (they ride along in every dump — better-auth lives
in the same database), your session and organizations are back too.

## If something is off

- **`pg_dump`/`pg_restore` not found** — install the PostgreSQL client tools
  or set `PG_BIN_DIR` in `.env` (Windows dev:
  `C:\Program Files\PostgreSQL\18\bin`).
- **`unrecognized configuration parameter` during restore** — a newer client
  restoring into an older server; harmless session settings only.
- **`must be owner of extension vector` during restore** — the pgvector
  extension is deliberately owned by the superuser (installed via
  `template1`), not by the `asep` role doing the restore; the extension stays
  put, which is exactly right. These two are the only errors the restore
  tolerates — anything else fails it.
- **Decryption errors after restore** — the `ENGINE_ENCRYPTION_KEY` in `.env`
  is not the one the backup was taken under. Find the right key; the data is
  fine.
- **The backup directory is empty** — backups were never enabled. That is the
  disaster this runbook cannot fix; enable `BACKUP_ENABLED=1` today.
