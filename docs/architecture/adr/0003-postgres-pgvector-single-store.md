# ADR-0003: PostgreSQL 16 + pgvector as the single system of record

**Status:** Accepted · **Date:** 2026-07-02

## Context

We need several kinds of storage: relational data (users, organizations,
repositories, conversations, runs, tasks), vector search for repository
intelligence, full-text search, and somewhere to keep LangGraph's checkpoints.
Standing up a separate datastore for each of these early in the project would add
real operational cost without giving users anything in return.

## Decision

One PostgreSQL 16 database, with the pgvector extension enabled from migration
0001, serves as the system of record, the vector store, and the checkpoint store
all at once. The engine reaches it through SQLAlchemy 2 (async, on psycopg 3),
and schema changes go through Alembic. Vector access sits behind a small retriever
interface, so if we ever need to move vectors elsewhere, the change stays
contained.

## Alternatives considered

- **A dedicated vector database** (Qdrant, Weaviate, or Milvus) would give better
  approximate-nearest-neighbor performance and filtering at large scale, but it is
  another service to run, and it splits code metadata from the vectors — which
  forces cross-store joins for hybrid search. Worth revisiting past roughly ten
  million chunks, or if pgvector latency starts to hurt.
- **SQLite in dev with Postgres in production** would diverge in behavior
  (extensions, concurrency) badly enough to undermine the whole point of a
  production-like development environment.
- **Elasticsearch for text search** brings powerful BM25 ranking but is heavy to
  operate. Postgres full-text search is good enough for the hybrid retrieval we
  need, and it can be fused with vector search in a single query.

## Consequences

- One backup-and-restore story, and transactional consistency between metadata
  and vectors.
- Postgres becomes the scaling bottleneck to keep an eye on. The mitigations, in
  order, are better indexes and HNSW, then read replicas, then extracting the
  vector workload behind the retriever interface.
- The pgvector image (`pgvector/pgvector:pg16`) replaces the stock Postgres image
  in development.
