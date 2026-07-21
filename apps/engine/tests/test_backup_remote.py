"""Off-host backups: verified dumps shipped to S3-compatible storage.

Three layers: the pure logic runs anywhere (CI included); the upload/list/prune
round trip runs against the dev compose MinIO and skips when it is down; the
create_backup wiring proves the upload fires exactly when configured (it needs
pg_dump, so it skips where the client tools are absent, like the sibling suite).
Design note: docs/architecture/BACKUPS_AND_RECOVERY.md.
"""

import uuid
from contextlib import suppress

import boto3
import psycopg
import pytest
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from psycopg import sql

from engine import backup_remote
from engine.backup import BackupError, create_backup, find_pg_binary
from engine.config import get_settings

_MINIO_ENDPOINT = "http://localhost:9000"
_MINIO_KEY = "minioadmin"


# ── Pure logic: no MinIO, no Postgres — these run in CI ──────────────────────


def test_remote_enabled_follows_the_bucket_setting(monkeypatch):
    monkeypatch.setattr(get_settings(), "backup_s3_bucket", "")
    assert backup_remote.remote_enabled() is False
    monkeypatch.setattr(get_settings(), "backup_s3_bucket", "asep-backups")
    assert backup_remote.remote_enabled() is True


def test_pruning_zero_keep_touches_nothing():
    # keep<=0 must not even reach for a client (no MinIO in CI to reach).
    assert backup_remote.prune_remote_backups(keep=0) == []


def test_object_key_sits_under_the_prefix(monkeypatch):
    monkeypatch.setattr(get_settings(), "backup_s3_prefix", "team/asep")
    assert (
        backup_remote._key("asep-20260101T000000Z.dump") == "team/asep/asep-20260101T000000Z.dump"
    )
    monkeypatch.setattr(get_settings(), "backup_s3_prefix", "")
    assert backup_remote._key("asep-20260101T000000Z.dump") == "asep-20260101T000000Z.dump"


# ── Round trip against the dev MinIO (skips when it is not running) ──────────


def _minio_or_skip(monkeypatch):
    """A MinIO client and a fresh bucket, with settings pointed at them — or
    skip. Short timeouts and no retries so a missing MinIO skips fast."""
    client = boto3.client(
        "s3",
        endpoint_url=_MINIO_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id=_MINIO_KEY,
        aws_secret_access_key=_MINIO_KEY,
        config=BotoConfig(connect_timeout=1, read_timeout=2, retries={"max_attempts": 0}),
    )
    bucket = f"asep-test-{uuid.uuid4().hex[:10]}"
    try:
        client.create_bucket(Bucket=bucket)
    except (BotoCoreError, ClientError):
        pytest.skip("MinIO is not available")

    settings = get_settings()
    monkeypatch.setattr(settings, "backup_s3_bucket", bucket)
    monkeypatch.setattr(settings, "backup_s3_endpoint_url", _MINIO_ENDPOINT)
    monkeypatch.setattr(settings, "backup_s3_access_key_id", _MINIO_KEY)
    monkeypatch.setattr(settings, "backup_s3_secret_access_key", _MINIO_KEY)
    monkeypatch.setattr(settings, "backup_s3_region", "us-east-1")
    monkeypatch.setattr(settings, "backup_s3_prefix", f"test/{uuid.uuid4().hex[:8]}")
    return client, bucket


def _empty_and_delete_bucket(client, bucket: str) -> None:
    with suppress(Exception):
        objects = client.list_objects_v2(Bucket=bucket).get("Contents", [])
        if objects:
            client.delete_objects(
                Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in objects]}
            )
        client.delete_bucket(Bucket=bucket)


def test_upload_list_and_prune_round_trip(tmp_path, monkeypatch):
    client, bucket = _minio_or_skip(monkeypatch)
    try:
        names = [f"asep-2026010{i}T000000Z.dump" for i in range(1, 5)]
        for name in names:
            path = tmp_path / name
            path.write_bytes(b"dump-" + name.encode())
            backup_remote.upload_backup(path)

        listed = [key.rsplit("/", 1)[-1] for key in backup_remote.list_remote_backups()]
        assert listed == sorted(names, reverse=True)  # newest first

        removed = backup_remote.prune_remote_backups(keep=2)
        assert len(removed) == 2  # the two oldest
        remaining = [key.rsplit("/", 1)[-1] for key in backup_remote.list_remote_backups()]
        assert remaining == sorted(names, reverse=True)[:2]
    finally:
        _empty_and_delete_bucket(client, bucket)


# ── create_backup wiring: the upload fires exactly when configured ──────────


def _pg_tools_available() -> bool:
    try:
        find_pg_binary("pg_dump")
        find_pg_binary("pg_restore")
        return True
    except BackupError:
        return False


needs_pg = pytest.mark.skipif(
    not _pg_tools_available(), reason="PostgreSQL client tools (pg_dump/pg_restore) not installed"
)


def _url(dbname: str) -> str:
    base, _, _ = get_settings().database_url.rpartition("/")
    return f"{base}/{dbname}"


def _admin() -> psycopg.Connection:
    return psycopg.connect(
        _url("postgres").replace("postgresql+psycopg", "postgresql"), autocommit=True
    )


@needs_pg
def test_create_backup_ships_off_host_when_configured(tmp_path, monkeypatch):
    """The dump is uploaded and remote copies pruned — proven by stubbing the
    remote calls (no MinIO needed), so the wiring is what is under test."""
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(backup_remote, "remote_enabled", lambda: True)
    monkeypatch.setattr(
        backup_remote, "upload_backup", lambda path: calls.append(("upload", path.name))
    )
    monkeypatch.setattr(
        backup_remote, "prune_remote_backups", lambda keep: calls.append(("prune", keep)) or []
    )
    monkeypatch.setattr(get_settings(), "backup_retention", 7)

    name = f"asep_remote_wiring_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        dump = create_backup(str(tmp_path), database_url=_url(name))
        assert ("upload", dump.name) in calls
        assert ("prune", 7) in calls
    finally:
        with _admin() as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@needs_pg
def test_create_backup_stays_local_when_not_configured(tmp_path, monkeypatch):
    uploaded: list[str] = []
    monkeypatch.setattr(backup_remote, "remote_enabled", lambda: False)
    monkeypatch.setattr(backup_remote, "upload_backup", lambda path: uploaded.append(path.name))

    name = f"asep_local_only_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        create_backup(str(tmp_path), database_url=_url(name))
        assert uploaded == []  # never reached for
    finally:
        with _admin() as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
