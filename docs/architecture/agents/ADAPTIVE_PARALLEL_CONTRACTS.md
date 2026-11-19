# Adaptive teams: parallel implementation contracts

This document locks the interfaces for the five worktrees in PLAN.md. The lead
owns migrations, database models/enums/RLS, API runs, preview credential API,
API registration, generated OpenAPI types, and final integration. Agents must not
edit those files. Existing steps 1 and 2 are retained and extended, not replaced.

## Shared data

`agents/teams_types.py` exports Complexity, Level (= SeatLevel), ModelChoice
(= ModelSelection), TriageResult (= TriageDecision), StageName, Seat, and
TeamTemplate. `db/enums.py` adds principal_engineer/release_engineer roles and
awaiting_deploy_approval/deploying statuses. A seat key is `role:level`.

Migration 0027 is the only new migration for this parallel batch. Run columns:
team (JSON list of Seat dicts), model_overrides (seat key to model id), design_note,
stages_completed (list of StageName strings), preview_requested (nullable bool:
None means infer from request), preview_options, preview_deployment,
deployment_status, deployment_approved_at/by/sha. Task columns: level and model.
Existing complexity, triage reason, test-only flag and report remain unchanged.

OrganizationModelPolicy is keyed by org_id with level_pins and
allow_open_source_auto. PreviewCredential is separately keyed by org_id with
created_by and encrypted_credentials; it must never be loaded as a model key.
Both tables have org-only FORCE RLS and standard timestamp fields.

## Models agent

Own llm/* (including catalog/evaluation), model fields in config.py, .env.example,
api/models.py, and new api/model_policy.py. Add tests and a unique design note.
Preserve resolve_seat(level, overrides=None, budget=None, org_overrides=None),
adding keyword `allow_open_source_auto=False`. The runner/assembler supplies
the run owner's provider keys and policy. ModelChoice fields remain compatible.
Expose policy endpoints GET/PUT /v1/model-policy (active org required, writes
admin-only); the lead registers the router. Add openai_compatible provider and
per-entry base_url, route it through LiteLLM's OpenAI adapter without breaking
credential lookup. Auto selection of open source requires org opt-in AND genuine
evaluation evidence covering the existing golden tasks/tool calls; a manually
set `evaluated` bool alone is insufficient. Provide a runnable evaluation command.

## Triage agent

Own agents/triage.py and agents/quick_team.py, triage prompts, triage/golden tests,
and a unique design note. Preserve existing classify_request/classify_rules,
is_test_only, scope_terms, template_for imports. Complexity/TriageDecision now
live in teams_types and must remain importable through triage for compatibility.
Implement quick_template(test_only=False) -> TeamTemplate; names are `quick` and
`test_report`. Include plan/build/sandbox/security/dependency/publish stages for
editing, plan/test_report for read-only work. Improve and evaluate rule coverage;
do not duplicate or edit runner.py. Report integration needs to the lead.

## Teams agent

Own agents/runner.py, registry.py, supervisor.py, product_manager.py, teams.py,
new principal agent/prompts, recovery.py, jobs.py, worker.py; add own tests/note.
Implement get_team_template(name) -> TeamTemplate and
async assemble_run_team(session, run) -> list[dict] (also assign run.team).
Templates: quick, test_report, standard, complex. Use the Quick provider above
and iterate configured stages. Resolve roster choices using the run owner's keys,
org level policy, per-seat overrides; persist task levels/models. The PM returns
task level; Complex gets a Principal design note and final review. Keep routing
deterministic and scans mandatory before any publish. Preserve report-only intent.
At the preview stage set awaiting_deploy_approval and return with a committed
checkpoint; never deploy without approved_at/by AND exact current approved SHA.
The API resumes EXECUTING after second approval. Stage checkpoints/recovery must
avoid duplicate deployment/publication and survive recovery through DEPLOYING.
Call Agent 5's helpers with encrypted credentials decrypted outside model context.
Cloud smoke evidence must reach the PR body. Expose cleanup orchestration hooks
for TTL/merge cleanup; coordinate requirements with the lead rather than changing
webhooks/main/API files.

## UI agent

Own apps/web only (run screen, BFF models/roster/deploy/policy routes, settings,
timeline), tests and a unique design note. Consume generated schema. Run detail
contains the fields above; team seat fields: key, role, level, model, reason.
PATCH /v1/runs/{id}/roster accepts {model_overrides:{seat_key:model_id}}; clearing
the map restores auto. PATCH triage remains available before approval. A roster
change returns full RunDetail; deploy-decision accepts {approved:boolean} and
returns RunOut. Show design note, roster/model choices, preview waiting/approval,
URL/smoke results and simulated-vs-live distinction. No secret readbacks. API
errors remain visible. The lead registers policy/credential routes if needed.

## Deploy agent

Own deploy/* except contracts.py, agents/release.py, new deploy-only tools functions
in agents/tools.py, Helm preview values/fixtures, own tests/note. Shared types are
in deploy/contracts.py. Implement deploy/preview.py exports:

* async deploy_preview(ws, credentials: dict[str,str], *, options:
  PreviewOptions|None=None) -> PreviewDeployment
* async run_cloud_smoke_tests(url, *, paths:list[str]|None=None,
  timeout_seconds:int=30) -> SmokeResult
* async teardown_preview(deployment: PreviewDeployment,
  credentials:dict[str,str]) -> None

Credentials contain `kubeconfig` plaintext only inside the deploy adapter, never
in LLM messages, prompts, tools results, logs, events, or errors. Validate
kubeconfig (reject exec/auth-provider hooks and external file refs); reject
unsafe repo charts/values before privileged Helm execution. Restrict namespaces
and release names to run-derived preview prefixes. Never production contexts or
arbitrary shell strings. Define deterministic, explicitly simulated mode for
LLM_FAKE/offline tests with no network and no fake assertion of a live URL.
Return bounded smoke evidence and expiry for cleanup. Real code must actually
deploy and tear down when configured, not just print commands. Report any new
dependency/settings needed to the lead; do not edit config/pyproject/contracts.

## Workflow and acceptance

Each agent writes its design note before code, uses only its owned files, runs
applicable checks, and commits changes to its prepared worktree. No nested agents,
PRs, pushes, or live cloud deployments by children. Return commit SHA, changed
files, test results, any unresolved contracts/stubs. Dependencies owned by others
may be stubbed in unit tests, not replaced in implementation. Parent integrates
Models, Triage, Deploy, Teams, UI and runs combined checks. No placeholder is
accepted in the finished result. Live provider/cluster validation requires actual
available access and must never be reported as passed by an offline simulation.
