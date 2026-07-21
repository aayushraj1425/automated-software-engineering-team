import { defineConfig } from "@playwright/test";

// Prereqs: dev services up (`pnpm db:up`) and migrations applied
// (`pnpm db:migrate`). The engine runs with LLM_FAKE=1 so no provider key
// is needed and the assistant reply is deterministic.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  forbidOnly: !!process.env.CI,
  use: {
    baseURL: "http://localhost:3000",
    // A red CI run leaves a replayable trace (`playwright show-trace`) —
    // the CI job uploads test-results/ as an artifact on failure.
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "uv run python -m engine.serve",
      cwd: "../engine",
      url: "http://localhost:8000/healthz",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { LLM_FAKE: "1" },
    },
    {
      command: "pnpm dev",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
