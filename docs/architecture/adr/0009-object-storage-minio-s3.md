# ADR-0009: Object storage — MinIO (dev) / any S3-compatible store (prod)

**Status:** Accepted · **Date:** 2026-07-02

## Context

The platform accumulates blobs: repository archives, agent-run artifacts (diffs, logs,
reports), and later generated documents and eval outputs. These don't belong in
Postgres rows or on ephemeral container disks.

## Decision

Standardize on the **S3 API**. Dev runs **MinIO** in compose; production can use AWS
S3, Cloudflare R2, or self-hosted MinIO — configuration is just endpoint + credentials
(`S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`). Engine access goes
through a thin `ObjectStore` wrapper so signing/retry policy lives in one place.

## Alternatives considered

- **Local filesystem volumes** — simplest, but ties artifacts to one node, complicates
  backups, and breaks the moment workers scale horizontally.
- **Postgres large objects / bytea** — one store to run, but bloats backups and WAL for
  data with no relational value.
- **Provider-specific SDK (AWS-only)** — closes the self-host door; S3 API is the
  de facto standard MinIO/R2 both speak.

## Consequences

- One more dev service (MinIO) — negligible.
- Bucket lifecycle rules (artifact retention) become part of Phase 7 ops work.
- Workspaces under `.workspaces/` remain local scratch space; anything worth keeping
  gets promoted to object storage.
