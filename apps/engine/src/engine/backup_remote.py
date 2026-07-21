"""Ship verified Postgres dumps off-host to S3-compatible object storage.

Off unless BACKUP_S3_BUCKET is set. Works against AWS S3, MinIO, R2, or any
S3-compatible endpoint through boto3 — BACKUP_S3_ENDPOINT_URL points it at a
non-AWS store (the dev compose MinIO). Credentials are taken from the two
BACKUP_S3_* settings when present (dev), else boto3's default chain, so a
production pod uses its IAM role and stores no secret.

Never the hot path, and never *before* the local dump is safe: create_backup
uploads only after the local file is written, verified, and pruned. A failed
upload raises so the nightly job surfaces it — the local backup is already kept.

Design note: docs/architecture/BACKUPS_AND_RECOVERY.md.
"""

from pathlib import Path

import boto3
import structlog

from engine.backup import DUMP_PATTERN
from engine.config import get_settings

log = structlog.get_logger()

# The writer's glob (asep-*.dump) split into the literal head and tail, so the
# remote list matches exactly the files create_backup produces.
_NAME_HEAD, _NAME_TAIL = DUMP_PATTERN.split("*")


def remote_enabled() -> bool:
    """Off-host upload happens only when a bucket is configured."""
    return bool(get_settings().backup_s3_bucket)


def _client():
    """An S3 client for the configured store. Explicit keys when set (dev
    MinIO), otherwise boto3's default credential chain (production IAM role)."""
    settings = get_settings()
    kwargs: dict[str, str] = {}
    if settings.backup_s3_endpoint_url:
        kwargs["endpoint_url"] = settings.backup_s3_endpoint_url
    if settings.backup_s3_region:
        kwargs["region_name"] = settings.backup_s3_region
    if settings.backup_s3_access_key_id and settings.backup_s3_secret_access_key:
        kwargs["aws_access_key_id"] = settings.backup_s3_access_key_id
        kwargs["aws_secret_access_key"] = settings.backup_s3_secret_access_key
    return boto3.client("s3", **kwargs)


def _key(name: str) -> str:
    """Object key for a dump file name, under the configured prefix."""
    prefix = get_settings().backup_s3_prefix.strip("/")
    return f"{prefix}/{name}" if prefix else name


def upload_backup(dump_path: Path) -> str:
    """Upload one verified dump to the bucket; returns the object key."""
    settings = get_settings()
    key = _key(dump_path.name)
    _client().upload_file(str(dump_path), settings.backup_s3_bucket, key)
    log.info("backup.uploaded", bucket=settings.backup_s3_bucket, key=key)
    return key


def list_remote_backups() -> list[str]:
    """Every dump object under the prefix, newest first (the timestamped
    names sort). Used by pruning and available to the runbook."""
    settings = get_settings()
    prefix = settings.backup_s3_prefix.strip("/")
    list_prefix = f"{prefix}/{_NAME_HEAD}" if prefix else _NAME_HEAD
    paginator = _client().get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=settings.backup_s3_bucket, Prefix=list_prefix):
        keys.extend(
            obj["Key"] for obj in page.get("Contents", []) if obj["Key"].endswith(_NAME_TAIL)
        )
    return sorted(keys, reverse=True)


def prune_remote_backups(keep: int) -> list[str]:
    """Keep the newest ``keep`` remote dumps, delete the rest — mirroring the
    local retention so the bucket does not grow without bound. Returns the
    keys removed."""
    if keep <= 0:
        return []
    settings = get_settings()
    stale = list_remote_backups()[keep:]
    if stale:
        _client().delete_objects(
            Bucket=settings.backup_s3_bucket,
            Delete={"Objects": [{"Key": key} for key in stale]},
        )
        log.info("backup.remote_pruned", removed=stale)
    return stale
