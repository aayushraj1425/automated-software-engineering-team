# ADR-0011: Adaptive teams and per-seat model selection

Status: Accepted; implementation integrated, live validation deferred by the user

Date: 2026-11-17

Amends: [ADR-0006](0006-litellm-model-router-and-cost.md)

## Context

[The adaptive teams plan](../../PLAN.md) separates a role's prompt and tool policy
from the model used to fill that seat. It must ship in runnable increments without
breaking existing runs or changing the deny-by-default tool policy in ADR-0008.

## Decision

Keep LiteLLM behind ModelRouter. Introduce an operator-configured model catalog
and support, engineer, senior, and principal seat levels. The registry maps legacy
cheap, coder, and planner roles to support, engineer, and senior respectively;
an explicit level can override this mapping. Complex templates include Principal
design and review of the final changes.

Selection precedence is seat override, organization override supplied by the caller,
server level pin, then cheapest available tool-capable model meeting minimum
strength. Hosted-model strength is operator-assigned metadata. Providers include
anthropic, openai, gemini and operator-configured openai_compatible endpoints.
Open source entries may be pinned manually; auto requires organization opt-in
and signed, current tool-probe and golden-task evidence. A configured evaluated
flag is insufficient. Certification proves at most engineer strength; senior and
principal seats remain excluded from open source auto selection.

An empty catalog preserves MODEL_PLANNER, MODEL_CODER, and MODEL_CHEAP. No new
model ids or prices are assumed from names in the proposal. Operators supply
models their accounts can actually use. Non-agent tier callers remain compatible.

Budget estimates use 8,000 input and 2,000 output tokens for a representative turn.
If no qualified model fits the remaining run budget, auto selection can lower one
seat level. Missing credentials alone never lower a level. Unavailable or
unaffordable pins fail explicitly. Estimates are routing hints, not reservations
or a guarantee that a provider response cannot exceed the cap. The existing run
spend checks remain; strict per-turn reservations are future work.

After existing transient/rate-limit retries, agent tool calls may fail over to an
available hosted model of exactly the same strength, sufficient context size,
and estimated cost no greater than the original. Authentication, invalid requests,
and other permanent failures
propagate. Each successful fallback records another selection event. Catalog
prices fill gaps in LiteLLM's cost table.

The runner binds a selected model to each agent invocation with a context variable
and resets it on every exit. Planning, implementation, revisions, review, and QA
record model.selected with the role, task where applicable, levels, model, reason,
and estimate. Offline mode truthfully records model=fake plus configured_model.
The timeline renders the model and reason. GET /v1/models exposes authenticated
catalog metadata. No schema migration is needed for this increment.

## Decisions for subsequent increments

1. Start preview deployment with a Kubernetes namespace using the existing Helm
   assets. Require separate deploy approval, keep credentials outside model context,
   and provide teardown. Hosts for repositories without charts follow later.
2. Keep plan approval for Quick test-only runs. Automatic approval can be a later
   explicit organization policy after the read-only execution boundary is proven.
3. Support an optional monthly organization budget later, alongside the per-run
   cap. Enforcement needs durable spend attribution and concurrent reservations;
   a UI setting alone would be misleading. Do not block step 1 on this work.

## Delivery boundary

Templates now drive execution and durable stage checkpoints. The approval screen
exposes complexity and model overrides; organization settings expose level pins
and the open source auto switch. Complex runs produce a design note and Principal
review. Preview deployment requires a second approval tied to the checked commit;
cloud credentials are decrypted outside model context. Validated manifests are
frozen before credentialed installation. Cleanup retries use both database records
and cluster expiry annotations.

The adapter needs a repository chart, an existing image and a preview cluster;
it does not build or push images. Live provider, cluster and local-model validation
is deferred by the user. Offline results neither certify a model nor prove a live
preview. See [Running adaptive teams](../agents/ADAPTIVE_TEAMS.md) for runnable checks.

## Validation

Routing tests cover key availability, pins, costs, budget downgrade, legacy
compatibility, and same-strength fallback with stubbed provider responses. API
tests exercise authenticated catalog access and an offline plan, approval,
implementation, review, and completion with durable per-agent selection events.
