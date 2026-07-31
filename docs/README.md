# Documentation

Start here. This folder has three layers: **guides** that orient you, **reference**
material that goes deep, and **process** records that track the work.

## Guides — read these first

| Guide | For |
|---|---|
| [How it works](HOW_IT_WORKS.md) | Understanding the product without reading code |
| [Getting started](getting-started.md) | Installing, configuring, and running it locally |
| [Architecture](architecture.md) | Understanding how the system is shaped and why |
| [Development](development.md) | Working in the codebase: conventions, testing, adding a feature |
| [API overview](api.md) | The engine's API surface and trust model |
| [Deployment](deployment.md) | Running it in production |
| [Troubleshooting](troubleshooting.md) | Fixing a common problem |

## Reference — depth on a specific topic

- [`architecture/`](architecture/README.md) — a design note per feature, one per
  file. Its [index](architecture/README.md) groups them by area, and
  [`OVERVIEW.md`](architecture/OVERVIEW.md) is the system-wide diagram set.
- [`architecture/adr/`](architecture/adr/) — Architecture Decision Records: the
  significant choices, each with the alternatives that were rejected.
- [`SECURITY.md`](SECURITY.md) — the security posture and boundaries.
- [`EVALUATION.md`](EVALUATION.md) — how the agent team is scored against golden tasks.
- [`runbooks/`](runbooks/) — operational procedures (e.g. disaster recovery).

## Process — what's planned and what shipped

- [`ROADMAP.md`](ROADMAP.md) — the phase plan and status.
- [`BACKLOG.md`](BACKLOG.md) — the living backlog; the Done section is a dated
  changelog of every shipped slice.
- [`OPERATOR_HANDOFF.md`](OPERATOR_HANDOFF.md) — the steps that need an operator's
  secret, infrastructure, or decision.

## How the docs are meant to be read

A design note is written *before* the code it describes, so it captures intent, not
just the result. When you're trying to understand a feature, read its note first —
it explains the "why" the code can't. When you're changing a feature, update its
note in the same change. A note that has drifted from the code is a bug in the
documentation.
