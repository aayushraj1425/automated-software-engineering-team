# Triage and Quick runs

Delivery step 2 of [Adaptive Agent Teams](../../PLAN.md) adds rules-first triage,
persisted complexity, report-only test runs, small single-engineer changes,
and escalation. Plan approval remains required for every run.

## Classification and approval

Before planning, triage matches request keywords and up to 100 relevant paths
from that repository's existing index. Deployment/migration/infrastructure requests
are Complex. Multiple matching services or more than eight matching files also
raise the complexity; three to eight files need Standard. Small renames and typo
corrections can be Quick. These path signals are heuristics, not semantic proof
of impact. Missing or stale indexes do not prevent a run.

Only ambiguous requests use the support seat's cheap model. Its token usage and
cost count toward the run; invalid classification JSON defaults to Standard.
Offline mode uses a deterministic Standard fallback. A model classification
cannot grant report-only status or bypass approval.

`POST /v1/runs` accepts an optional `complexity` (`quick`, `standard`, `complex`).
`PATCH /v1/runs/{id}/triage` changes it only while awaiting approval. The approval
screen exposes this control and displays the reason. A Quick editing board must
have no more than two active tasks assigned to one engineer. Plan edits and
classification edits take a row lock to serialize with approval. Every
classification/override is recorded as `run.triaged`.

## Test-only work

"Run the tests for login and tell me what fails" produces one QA task and a
deterministic approval plan, without a Product Manager or LLM call. Requests to
fix code, deploy, or migrate do not qualify as test-only. After approval, QA
invokes the existing sandbox runner directly. It has no editing or publishing
path. Sandbox execution copies the workspace into a disposable container; tests
cannot modify the repository or its jailed clone.

The current sandbox detects and runs the repository's test suite. It does not
derive shell commands or test filters from the request. The plan and report
explicitly state this scope. Test selection by feature is future work.

A completed report can contain passed, failed, or skipped tests. A failing test
suite is a successful diagnostic operation, not permission to repair it. Skips
(disabled sandbox, missing setup, unavailable Docker) remain visible and never
claim tests passed. Infrastructure failures retry up to three times; after the
second failure Quick becomes Standard, while the run remains report-only. If
the third attempt cannot execute, the run fails and retains the report.

`test_report` stores status, command, reason, exit code, scope, and bounded output.
It appears on the run page, the downloaded Markdown report, and the timeline
as `tests.reported`. There is no diff scan or PR for a report-only operation.
Changing its complexity never authorizes code edits.

## Small changes and escalation

A Quick editing run uses one engineer for read-only planning and implementation.
The engineer still has the existing workspace jail, tool allow-list, and model
selection rules. A plan requiring more than two tasks or another specialist
escalates before approval. The complete plan is kept for human review.

After approval, a growing board or two failed engineer attempts escalates Quick
to Standard, allowing the supervisor's next retry and the normal reviewer.
Needing QA to repair a failing sandbox also escalates; independent review follows
those repairs. The normal run budget still applies. Escalation is recorded once
as `run.escalated`; the final failure behavior remains bounded.

Quick changes that pass tests retain secret and dependency scans before publishing.
When there is no tracked diff, they complete without a branch publication or PR.
Standard and Complex requests use the existing full pipeline in this increment.
Principal Engineer behavior, general configurable templates, model overrides on
the approval screen, and preview deployments are still subsequent steps.

## Storage and migration

Migration 0026 adds nullable complexity/reason, a Standard-default template,
report-only flag, and test-report JSON to `agent_runs`. Existing runs retain the
Standard pipeline. No new role or status value is introduced. Recovery keeps
classification and report-only intent; a restarted report operation can safely
repeat sandbox execution.

Fresh installation verification also exposed old migrations 0004/0011 importing
the runtime embedding size. They now retain the historical 768 dimensions so
migration 0009 can build its historical HNSW index. Migration 0025 performs the
existing change to 3072 and removes that index. Already-upgraded databases are
unaffected by this historical correction.

## Run the checks

From the repository root, with Docker and uv installed:

```powershell
./scripts/check-model-catalog.ps1 -RealSandbox
```

The script starts disposable Postgres and Redis containers on random local
ports. It verifies fresh migrations and the new migration's downgrade/re-upgrade,
then runs the model, triage, Quick, Standard, approval, reporting, and recovery
checks. `-RealSandbox` adds a real one-test Python repository, executes it through
the approved Quick path in Docker, and checks that its report says `1 passed`.
This requires pulling the sandbox image and installing pytest. Without that flag,
sandbox outcomes are stubbed for deterministic checks of passed/failed/skipped
reports and infrastructure retries. No provider keys or cloud credentials are
required. All temporary containers and database environment overrides are cleaned
up on completion or failure.

For an existing development database, run `uv run alembic upgrade head` from
`apps/engine` before starting the updated engine. The verification script migrates
only its disposable database, not your development database.
