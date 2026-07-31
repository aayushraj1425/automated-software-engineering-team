# ADR-0009: Object storage — MinIO (dev) / any S3-compatible store (prod)

**Status:** Accepted · **Date:** 2026-07-02

## Context

The platform accumulates blobs over time: repository archives, agent-run artifacts
(diffs, logs, reports), and, later, generated documents and evaluation outputs.
None of these belong in Postgres rows or on a container's ephemeral disk.

## Decision

Standardize on the S3 API. Development runs MinIO in compose, and production can
use AWS S3, Cloudflare R2, or a self-hosted MinIO — the difference is just an
endpoint and credentials (`S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`,
`S3_BUCKET`). The engine reaches storage through a thin `ObjectStore` wrapper, so
signing and retry policy live in one place.

## Alternatives considered

- **Local filesystem volumes** are the simplest option, but they tie artifacts to
  a single node, complicate backups, and break the moment workers scale
  horizontally.
- **Postgres large objects or `bytea`** keep everything in one store, but they
  bloat backups and the write-ahead log with data that has no relational value.
- **A provider-specific SDK (AWS only)** would close the self-host door. The S3 API
  is the de facto standard that MinIO and R2 both speak, so there is no reason to
  lock in.

## Consequences

- One more service in development (MinIO), which is negligible.
- Bucket lifecycle rules for artifact retention become part of the Phase 7
  operations work.
- Workspaces under `.workspaces/` stay local scratch space; anything worth keeping
  gets promoted to object storage.
