"""Postgres backups: verified dumps, retention, and a tested restore path.

Drives the standard PostgreSQL tools (pg_dump / pg_restore) as subprocesses —
no custom format, so any Postgres operator can work with the files. Every
dump is verified (``pg_restore --list`` must read the archive) before it is
kept, and pruning only ever runs after a *successful* dump, so a failing
backup can never eat the good ones that came before it.

CLI (also the nightly cron in ``engine/worker.py`` when BACKUP_ENABLED=1):

    uv run python -m engine.backup create
    uv run python -m engine.backup verify  <dump-file>
    uv run python -m engine.backup restore <dump-file> --database-url <url>

Design note: docs/architecture/BACKUPS_AND_RECOVERY.md; the recovery
procedure lives in docs/runbooks/DISASTER_RECOVERY.md.
"""

import argparse
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy.engine.url import make_url

from engine.config import get_settings

log = structlog.get_logger()

DUMP_PATTERN = "asep-*.dump"
_WINDOWS_INSTALL_DIR = Path("C:/Program Files/PostgreSQL")


class BackupError(RuntimeError):
    """A backup or restore step failed; the message says which and why."""


def find_pg_binary(name: str) -> str:
    """Locate pg_dump/pg_restore: PG_BIN_DIR, then PATH, then the newest
    Windows install. A newer client than the server is fine (that is the
    supported direction); older is what pg_dump itself refuses."""
    bin_dir = get_settings().pg_bin_dir
    if bin_dir:
        candidate = Path(bin_dir) / name
        for path in (candidate, candidate.with_suffix(".exe")):
            if path.is_file():
                return str(path)
        raise BackupError(f"{name} not found in PG_BIN_DIR ({bin_dir})")

    on_path = shutil.which(name)
    if on_path:
        return on_path

    installs = sorted(
        _WINDOWS_INSTALL_DIR.glob(f"*/bin/{name}.exe"),
        key=lambda p: int(p.parent.parent.name) if p.parent.parent.name.isdigit() else 0,
    )
    if installs:
        return str(installs[-1])

    raise BackupError(f"{name} not found — install the PostgreSQL client tools or set PG_BIN_DIR")


def _connection(database_url: str) -> tuple[list[str], dict[str, str], str]:
    """Split a SQLAlchemy URL into pg_dump/pg_restore connection flags, the
    PGPASSWORD env (never on the command line), and the database name."""
    url = make_url(database_url)
    if not url.database:
        raise BackupError("the database URL names no database")
    flags = [
        "--host",
        url.host or "localhost",
        "--port",
        str(url.port or 5432),
        "--username",
        url.username or "postgres",
        "--no-password",  # never prompt; a missing PGPASSWORD should fail loudly
    ]
    return flags, {"PGPASSWORD": url.password or ""}, url.database


def _execute(binary: str, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — args are built here, not user input
        [binary, *args],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )


def _run(binary: str, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = _execute(binary, args, env)
    if result.returncode != 0:
        tool = Path(binary).stem
        raise BackupError(f"{tool} failed: {result.stderr.strip()[:500]}")
    return result


def create_backup(backup_dir: str | None = None, database_url: str | None = None) -> Path:
    """Dump the database to a timestamped, verified file; prune old ones.

    The dump lands in a ``.part`` file and is renamed only after pg_dump exits
    cleanly and the archive verifies, so a crash mid-dump never leaves a
    plausible-looking broken backup behind.
    """
    settings = get_settings()
    directory = Path(backup_dir or settings.backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    flags, env, dbname = _connection(database_url or settings.database_url)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dump_path = directory / f"asep-{stamp}.dump"
    part_path = dump_path.with_suffix(".part")

    try:
        _run(
            find_pg_binary("pg_dump"),
            ["--format=custom", *flags, "--dbname", dbname, "--file", str(part_path)],
            env,
        )
        verify_backup(part_path)
    except BackupError:
        part_path.unlink(missing_ok=True)
        raise
    part_path.rename(dump_path)

    removed = prune_backups(directory, keep=settings.backup_retention)
    log.info(
        "backup.created",
        file=dump_path.name,
        bytes=dump_path.stat().st_size,
        pruned=[p.name for p in removed],
    )
    return dump_path


def verify_backup(dump_path: Path) -> int:
    """Prove the archive is readable without touching a database: pg_restore
    --list must parse it. Returns the number of archive entries."""
    if not dump_path.is_file():
        raise BackupError(f"no such backup file: {dump_path}")
    result = _run(find_pg_binary("pg_restore"), ["--list", str(dump_path)], env={})
    entries = [line for line in result.stdout.splitlines() if line and not line.startswith(";")]
    if not entries:
        raise BackupError(f"backup lists no contents: {dump_path.name}")
    return len(entries)


def restore_backup(dump_path: Path, database_url: str) -> None:
    """Restore a dump into an *existing* database (the runbook creates it).

    ``--clean --if-exists`` drops what the dump is about to recreate, so
    restoring over a partly-broken database works; ``--no-owner`` keeps the
    restore working when the restore role differs from the dump's owner.
    """
    verify_backup(dump_path)  # refuse to point pg_restore at a broken archive
    flags, env, dbname = _connection(database_url)
    result = _execute(
        find_pg_binary("pg_restore"),
        [
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            # COMMENT ON EXTENSION needs to *own* the extension — which the
            # restoring role deliberately does not (vector is installed by the
            # superuser via template1). Comments are noise in a recovery.
            "--no-comments",
            *flags,
            "--dbname",
            dbname,
            str(dump_path),
        ],
        env,
    )
    if result.returncode != 0:
        # Two narrow tolerances, both artifacts of restoring as the
        # non-superuser engine role (ROW_LEVEL_SECURITY.md) — neither touches
        # restored data, and the round-trip test reads rows back to prove it:
        #  - a newer pg_restore opens its session with settings an older
        #    server does not know (PG18 client → PG16: SET transaction_timeout)
        #  - DROP/ALTER on the vector extension, which is deliberately owned
        #    by the superuser (installed via template1) and must stay put
        # Any other error (a table that failed, a broken archive) still
        # fails the restore.
        errors = [
            line for line in result.stderr.splitlines() if line.startswith("pg_restore: error:")
        ]
        harmless = ("unrecognized configuration parameter", "must be owner of extension")
        if not errors or any(not any(h in e for h in harmless) for e in errors):
            raise BackupError(f"pg_restore failed: {result.stderr.strip()[:500]}")
        log.warning("backup.restore_skipped_harmless_errors", count=len(errors))
    log.info("backup.restored", file=dump_path.name, database=dbname)


def prune_backups(directory: Path, keep: int) -> list[Path]:
    """Keep the newest ``keep`` dumps (the timestamped names sort), delete the
    rest. Returns what was removed."""
    if keep <= 0:
        return []
    dumps = sorted(directory.glob(DUMP_PATTERN), key=lambda p: p.name, reverse=True)
    removed = dumps[keep:]
    for path in removed:
        path.unlink(missing_ok=True)
    return removed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="engine.backup", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("create", help="dump, verify, and prune")
    verify = commands.add_parser("verify", help="prove a dump file is readable")
    verify.add_argument("file", type=Path)
    restore = commands.add_parser("restore", help="restore a dump into an existing database")
    restore.add_argument("file", type=Path)
    restore.add_argument(
        "--database-url",
        required=True,
        help="explicit target — restoring is destructive, so it is never implied",
    )

    args = parser.parse_args(argv)
    if args.command == "create":
        print(create_backup())
    elif args.command == "verify":
        print(f"ok: {verify_backup(args.file)} archive entries")
    elif args.command == "restore":
        restore_backup(args.file, args.database_url)
        print(f"restored {args.file.name}")


if __name__ == "__main__":
    main()
