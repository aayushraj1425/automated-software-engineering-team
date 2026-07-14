"""Backups: the restore path is exercised on every push, not during an outage.

The round-trip test drives the real pg_dump/pg_restore against a scratch
database it creates itself (never asep_test — other tests are using it),
restores the dump into a *second* scratch database, and reads the data back
from the copy. Machines without the PostgreSQL client tools skip cleanly.
Design note: docs/architecture/BACKUPS_AND_RECOVERY.md.
"""

import uuid

import psycopg
import pytest
from psycopg import sql

from engine.backup import (
    BackupError,
    create_backup,
    find_pg_binary,
    prune_backups,
    restore_backup,
    verify_backup,
)
from engine.config import get_settings


def _pg_tools_available() -> bool:
    try:
        find_pg_binary("pg_dump")
        find_pg_binary("pg_restore")
        return True
    except BackupError:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_tools_available(), reason="PostgreSQL client tools (pg_dump/pg_restore) not installed"
)


def _url(dbname: str) -> str:
    """The test server's URL pointed at another database on it."""
    base, _, _ = get_settings().database_url.rpartition("/")
    return f"{base}/{dbname}"


def _connect(dbname: str, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(
        _url(dbname).replace("postgresql+psycopg", "postgresql"), autocommit=autocommit
    )


def _recreate_database(admin: psycopg.Connection, name: str) -> None:
    admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _drop_database(admin: psycopg.Connection, name: str) -> None:
    admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def test_backup_round_trip_restores_the_data(tmp_path):
    """The exit criterion: a row written before the dump comes back from a
    database restored *from* that dump."""
    source, target = "asep_backup_source", "asep_backup_target"
    marker = f"backup-proof-{uuid.uuid4().hex[:8]}"

    with _connect("postgres", autocommit=True) as admin:
        _recreate_database(admin, source)
        _recreate_database(admin, target)
    try:
        with _connect(source) as conn:
            conn.execute("CREATE TABLE proof (note text)")
            conn.execute("INSERT INTO proof VALUES (%s)", (marker,))

        dump = create_backup(str(tmp_path), database_url=_url(source))
        assert dump.is_file() and dump.suffix == ".dump"
        assert verify_backup(dump) > 0

        restore_backup(dump, _url(target))
        with _connect(target) as conn:
            row = conn.execute("SELECT note FROM proof").fetchone()
        assert row == (marker,)
    finally:
        with _connect("postgres", autocommit=True) as admin:
            _drop_database(admin, source)
            _drop_database(admin, target)


def test_a_failed_dump_cleans_up_and_keeps_old_backups(tmp_path):
    """A failing backup must never leave a half-written file behind, and must
    never prune the good backups that came before it."""
    keeper = tmp_path / "asep-20260101T000000Z.dump"
    keeper.write_bytes(b"an existing backup")

    with pytest.raises(BackupError, match="pg_dump failed"):
        create_backup(str(tmp_path), database_url=_url("asep_database_that_does_not_exist"))

    assert keeper.read_bytes() == b"an existing backup"
    assert list(tmp_path.glob("*.part")) == []


def test_verify_rejects_a_corrupt_file(tmp_path):
    bad = tmp_path / "asep-20260101T000000Z.dump"
    bad.write_bytes(b"not a postgres archive")
    with pytest.raises(BackupError, match="pg_restore failed"):
        verify_backup(bad)


def test_verify_rejects_a_missing_file(tmp_path):
    with pytest.raises(BackupError, match="no such backup"):
        verify_backup(tmp_path / "never-written.dump")


def test_restore_refuses_a_broken_archive(tmp_path):
    """Restore verifies first — pg_restore is never pointed at garbage."""
    bad = tmp_path / "asep-20260101T000000Z.dump"
    bad.write_bytes(b"garbage")
    with pytest.raises(BackupError):
        restore_backup(bad, _url("irrelevant_never_reached"))


def test_prune_keeps_the_newest_dumps(tmp_path):
    names = [f"asep-2026010{i}T000000Z.dump" for i in range(1, 6)]
    for name in names:
        (tmp_path / name).touch()
    (tmp_path / "unrelated.txt").touch()

    removed = prune_backups(tmp_path, keep=2)

    assert sorted(p.name for p in removed) == names[:3]
    assert sorted(p.name for p in tmp_path.glob("asep-*.dump")) == names[3:]
    assert (tmp_path / "unrelated.txt").exists()  # only dump files are managed


def test_prune_disabled_keeps_everything(tmp_path):
    (tmp_path / "asep-20260101T000000Z.dump").touch()
    assert prune_backups(tmp_path, keep=0) == []
    assert len(list(tmp_path.glob("asep-*.dump"))) == 1
