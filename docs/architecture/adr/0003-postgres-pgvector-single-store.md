# ADR-0003: PostgreSQL 16 + pgvector as the single system of record

**Status:** Accepted · **Date:** 2026-07-02

## Context

We need relational data (users, orgs, repos, conversations, runs, tasks), vector search
for repository intelligence (M2), full-text search, and LangGraph checkpoint storage.
Operating many datastores early adds cost with no user value.

## Decision

**One PostgreSQL 16 database** with the **pgvector** extension (enabled from migration
0001) serves as system of record, vector store, and checkpoint store. Access from the
engine via SQLAlchemy 2 async on psycopg3; schema migrations via Alembic. Vector access
will hide behind a small retriever interface (M2) so the store can be swapped.

## Alternatives considered

- **Dedicated vector DB (Qdrant/Weaviate/Milvus)** — better ANN performance and
  filtering at large scale, but another service to run, and it splits code metadata from
  vectors, forcing cross-store joins for hybrid search. Revisit past ~10M chunks or if
  pgvector latency hurts.
- **SQLite (dev) + Postgres (prod)** — divergent behavior (extensions, concurrency)
  undermines the walking-skeleton goal of prod-like dev.
- **Elasticsearch for text search** — powerful BM25, heavy operationally; Postgres FTS
  is adequate for M2's hybrid retrieval and can be fused with vectors in one query.

## Consequences

- One backup/restore story, transactional consistency between metadata and vectors.
- Postgres becomes the scaling bottleneck to watch; mitigations in order: indexes/HNSW,
  read replicas, then extract the vector workload behind the retriever interface.
- pgvector image (`pgvector/pgvector:pg16`) replaces the stock postgres image in dev.
