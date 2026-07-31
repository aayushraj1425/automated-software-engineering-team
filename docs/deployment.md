# Deployment

ASEP is built to run on Kubernetes with a Helm chart, but the pieces are ordinary
containers, so nothing here is Kubernetes-specific in spirit. This guide covers the
production topology and the handful of steps that only an operator can complete.
The detailed design is in
[`architecture/operations/KUBERNETES_DEPLOY.md`](architecture/operations/KUBERNETES_DEPLOY.md), and the
things that still need a human decision are collected in
[`OPERATOR_HANDOFF.md`](OPERATOR_HANDOFF.md).

## Images

Two images, both defined under `infra/docker/`:

- **`engine.Dockerfile`** builds one image that serves three roles by command: the
  API, the arq worker, and the migration job. Building them from one image keeps
  the three in lockstep — they can never run mismatched code.
- **`web.Dockerfile`** builds the Next.js standalone output.

CI builds and smoke-checks both on every push.

## The Helm chart

The chart lives in `infra/helm/asep`. What it renders:

- **Engine and web deployments**, each with a `/healthz` liveness/readiness probe.
- **A pre-upgrade migration job** so the schema is current before new pods serve
  traffic. (This is exactly the path a real CI run once caught an Alembic
  transaction bug on — the migration job is not decorative.)
- **One Secret** mirroring the `.env` contract, so configuration is expressed the
  same way in every environment.
- **The engine kept ClusterIP-only**, never exposed outside the cluster; only the
  web app has an ingress. The engine trusts the BFF, so the BFF is the only thing
  that should reach it.
- **An optional NetworkPolicy** (`engine.networkPolicy.enabled=true`) that
  restricts engine ingress to the web pods — the network-isolation half of the
  BFF-trust model.

Render it before applying to see exactly what you'll get:

```sh
helm template infra/helm/asep -f your-values.yaml
```

## Configuration in production

The same `.env` variables from [Getting started](getting-started.md#configuration)
apply, delivered through the chart's Secret. The ones that matter more in
production than in dev:

- **`ENGINE_ENCRYPTION_KEY`** — set a real 32-byte key. In dev it's derived from
  the service secret and the engine warns; in production that warning is a finding.
- **`DATABASE_URL_API`** — always set the non-owner role so user sessions can't
  bypass row-level security.
- **`RATE_LIMIT_SHARED=1`** — puts the rate-limit bucket in Redis so replicas share
  one window instead of one bucket each.
- **`BACKUP_S3_BUCKET`** — ships each verified nightly dump off-host, so a backup
  survives a lost node, not just a bad migration.
- **`OTEL_ENABLED=1`** with a collector endpoint — turns on request, LLM, and
  agent-run tracing plus the cost metric the alerting rules watch.

## Observability and backups

- **Metrics and traces** flow over OTLP when `OTEL_ENABLED=1`. A reference
  collector config and Prometheus alerting rules (error rate, p95 latency, LLM
  spend) live in `infra/monitoring/`. See
  [`architecture/operations/ALERTING.md`](architecture/operations/ALERTING.md).
- **Backups** are verified nightly `pg_dump`s with a tested restore path and a
  runbook: [`architecture/operations/BACKUPS_AND_RECOVERY.md`](architecture/operations/BACKUPS_AND_RECOVERY.md)
  and [`runbooks/DISASTER_RECOVERY.md`](runbooks/DISASTER_RECOVERY.md).

## What still needs an operator

A few things can't be built and verified from the code alone — they need a secret,
a running piece of infrastructure, or a judgment call. They're gathered, each with
its prerequisite, in [`OPERATOR_HANDOFF.md`](OPERATOR_HANDOFF.md). The two genuinely
open ones:

- **Mutual TLS between the BFF and the engine** — the stronger half of the trust
  boundary. The network-policy half ships; mTLS needs a certificate authority
  (cert-manager or a service mesh) in a real cluster.
- **Resource limits** — the chart ships placeholder CPU/memory requests. Size them
  against benchmark numbers under your expected load rather than guesses.

Everything else in that document is *built and tested* and just needs turning on:
the real-model evaluation workflow, the alerting rules, off-host backups, and the
in-cluster QA sandbox.
