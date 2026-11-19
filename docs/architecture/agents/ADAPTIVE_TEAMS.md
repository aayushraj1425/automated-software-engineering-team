# Running adaptive teams

Quick, Standard and Complex runs use different stage lists. Roles control prompts
and tools; a seat's level controls model selection. The approval screen shows the
roster, model choices and Principal Engineer design note. Quick test-only requests
still require approval and produce a report without editing or publishing code.

Start the application with the existing repository setup:

```sh
pnpm install
pnpm db:up
pnpm db:migrate
pnpm dev
```

Copy `.env.example` to `.env` first and configure the normal sign-in and service
secrets. `LLM_FAKE=1` enables offline model responses. An empty `MODEL_CATALOG`
keeps the existing planner/coder/cheap model configuration. To configure real
seat models, follow [Model catalog setup](MODEL_CATALOG.md).

## Reproducible checks

On Windows, from the repository root:

```powershell
./scripts/check-model-catalog.ps1 -FullSuite -Golden -RealSandbox
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web test
pnpm --filter web build
```

The engine script creates disposable PostgreSQL and Redis containers, verifies
migration upgrade/downgrade/upgrade, runs tests and writes
`test-results/adaptive-golden-fake.json`. `-RealSandbox` also exercises the Docker
test runner. Fake models verify pipeline mechanics, not generated-code quality or
cloud deployment. Run `-LiveModels` instead of `-Golden` for the three real-model
golden tasks, with configured provider access and a $2 cap per task. This also
requires Docker sandbox execution and writes `adaptive-golden-live.json`.

Windows web builds use `pnpm --filter web start` after building. The Linux
production image generates and runs Next.js standalone output; native Windows
builds avoid the symlinks required by standalone packaging.

Triage coverage can be checked without a database, from `apps/engine`:

```sh
uv run python -m engine.agents.triage_eval --split holdout --min-accuracy 0.9
```

This reports accuracy on the labelled fixture set, not a blind production sample.

## Preview deployment

Use an active organization. An owner or admin saves its preview kubeconfig in
Settings. The form is write-only: the engine encrypts the credential and returns
only configuration metadata. Use a self-contained preview kubeconfig with embedded
credentials; executable authentication plugins and external credential files are
unsupported. Credentials are never passed to an agent or included in events.

The engine and worker need Helm and kubectl. The production engine image includes
both. Native development installs can follow the official
[Helm](https://helm.sh/docs/intro/install/) and
[kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/) instructions.

On the new-run form, choose **Request a preview** and set the chart path, optional
values file, published image, lifetime and smoke paths. The API equivalent is:

```json
{
  "request": "Implement the feature and deploy its preview",
  "repository_url": "https://github.com/your-org/your-repo",
  "preview_requested": true,
  "preview_options": {
    "chart_path": "deploy/helm",
    "image": "registry.example/your-app:reviewed-commit",
    "ttl_hours": 24,
    "smoke_paths": ["/healthz"]
  }
}
```

The image must already be published, or defined in the chart's values. This
adapter deploys charts; it does not build or push application images. Its image
override is a string at `.Values.image`, which the chart must support. A minimal
compatible fixture is `infra/helm/asep-preview-fixture`.

Complex runs complete build, review, tests and scans, then pause for a separate
deployment approval. Inspect the diff and preview settings before approving. The
approved commit must match the checked workspace. A deployed URL and smoke results
appear on the run and in the generated pull-request body. Missing configuration
fails explicitly. `LLM_FAKE=1` produces a labelled simulation with no live URL.

Preview namespaces have an expiry. Maintenance and worker jobs retry teardown;
GitHub's signed merged-PR webhook also triggers cleanup. Other source hosts use
expiry cleanup. `PREVIEW_ALLOW_LOCAL_CLUSTER` and `PREVIEW_ALLOW_PRIVATE_SMOKE`
are explicit operator settings for local or private environments. See
[Preview adapter](PREVIEW_DEPLOY_ADAPTER.md) for chart restrictions and configuration.

## Open source models

An operator configures `openai_compatible` catalog entries for Ollama, vLLM or
another compatible endpoint. They may be pinned manually. Auto selection requires
both the organization opt-in and current signed evidence from a real evaluation:

```sh
cd apps/engine
uv run python scripts/eval_open_model.py openai_compatible/your-model
```

The database must be running. Use `--probes-only` for a preliminary check; it does
not certify a model. Fake runs cannot create valid evaluation evidence. See
[Open source models](OPEN_SOURCE_MODELS.md) for endpoint keys, evidence expiry and
the current engineer-level certification limit.

The optional monthly organization budget remains deferred. Per-run spending caps
apply; model-selection estimates are not durable reservations for concurrent calls.

## Verification recorded on 2026-11-17

- Combined engine suite: 911 passed, 5 skipped. The final Quick roster change also
  passed the complete adaptive-runtime file (39 cases).
- Web suite: 169 passed. Ruff, Pyright, ESLint, formatting and TypeScript checks pass.
- Quick, Standard and Complex offline golden runs all passed with real Docker
  sandbox tests. The generated scorecard is `test-results/adaptive-golden-fake.json`.
- Migration upgrade/downgrade/upgrade and generated API reproducibility pass.
- Native Windows web build and both Linux production image builds pass.
- Container startup: engine `/healthz` and web `/sign-in` return 200; the model BFF
  returns 401 without a session. The generated engine API includes the new routes.
- The fixture chart passes real Helm 4.3.1 rendering and policy checks, including
  inside the engine image with networking disabled.

Live provider, preview-cluster and local-model checks are deferred by the user.
No open source model has been certified and no live preview is claimed.
