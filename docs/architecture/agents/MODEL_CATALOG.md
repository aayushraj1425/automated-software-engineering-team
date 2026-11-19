# Model catalog and seats

Step 1 of [Adaptive Agent Teams](../../PLAN.md) is runnable with the existing
development setup. See [ADR-0011](../adr/0011-adaptive-teams-and-seat-models.md)
for selection rules and the decisions for later steps.

## Run with the existing configuration

Leave MODEL_CATALOG unset or set it to `[]`. The configured MODEL_PLANNER,
MODEL_CODER, and MODEL_CHEAP keep working. Start the platform using
[Getting started](../../getting-started.md), create a run, and approve its plan.
The timeline now includes each agent's model and selection reason.

With LLM_FAKE=1 the whole pipeline still runs without provider keys. Selection
events say `fake` and include the configured model separately. This exercises
the pipeline, not provider availability or model quality.

## Enable catalog selection

Set MODEL_CATALOG to a JSON array in `.env`. Each entry has these fields:

```json
{
  "id": "anthropic/your-enabled-model-id",
  "provider": "anthropic",
  "context_size": 200000,
  "supports_tools": true,
  "strength": 4,
  "input_cost_per_million": 3,
  "output_cost_per_million": 15,
  "open_source": false,
  "evaluated": false
}
```

The id and prices above are placeholders: supply the exact LiteLLM model id,
context size, and prices for your provider. Prices are USD per million tokens.
The catalog is supplied by the operator and is not provider discovery. The engine
validates structure and duplicate ids; it cannot verify provider access until
the first call. Configure provider keys through the existing settings page or
ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY. Caller keys take precedence.

Provide models meeting strength 1 for support, 3 for engineers, 4 for seniors,
and 5 for principals when using that level. Stronger models may fill lower
levels. A single strength-4 entry covers the Standard team; Principal seats use
strength 5 unless the budget rule lowers their level. Selection requires
tool support. Missing suitable models or keys fails the run with a clear error.

Optional server pins use a JSON map:

```dotenv
MODEL_LEVEL_PINS='{"senior":"anthropic/your-enabled-model-id"}'
```

Every pin must reference the catalog. Organization level pins and the open source
auto-selection switch are available through `GET/PUT /v1/model-policy`; writes
require an organization owner or admin. See [Open source models](OPEN_SOURCE_MODELS.md)
for endpoint configuration and signed evaluation requirements. Restart the engine
and worker after configuration changes. Authenticated `GET /v1/models` returns
the catalog, or an empty list in legacy mode.

Cost estimates cover a representative turn, not a complete agent task. Auto
selection can lower one level under budget pressure. Pins are never silently
replaced with weaker models. Actual run spend checks remain in effect.

## Verify locally

For a self-contained offline check on Windows, run from the repository root:

```powershell
./scripts/check-model-catalog.ps1
```

This requires Docker and uv. It starts disposable PostgreSQL and Redis containers
on random local ports, verifies migrations, runs the catalog and affected pipeline
tests, then stops and removes the containers. It leaves existing databases untouched and restores the
calling process's database environment variables. This also avoids conflicts
with a local PostgreSQL service on port 5433.

Use `./scripts/check-model-catalog.ps1 -RealSandbox` to also execute a real
Docker-backed Quick test report. See [Triage and Quick runs](TRIAGE_AND_QUICK_RUNS.md).

From `apps/engine`:

```powershell
uv run pytest tests/test_model_catalog.py tests/test_model_router.py -q
```

For the database-backed end-to-end check, start the development Postgres and
Redis (`pnpm db:up` from the repository root), then run from `apps/engine`:

```powershell
uv run pytest tests/test_model_catalog_api.py -q
```

The integration test creates an offline run, approves it, checks completion,
and verifies the planner, three engineers, and reviewer selection events. It
uses the test database, resets its schema, and creates jailed temporary git
workspaces. No provider calls or cloud deployments occur.
