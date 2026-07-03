import { defineConfig } from "@playwright/test";

// Prereqs: dev services up (`pnpm db:up`) and migrations applied
// (`pnpm db:migrate`). The engine runs with LLM_FAKE=1 so no provider key
// is needed and the assistant reply is deterministic.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  use: {
    baseURL: "http://localhost:3000",
  },
  webServer: [
    {
      command: "uv run python -m engine.serve",
      cwd: "../engine",
      url: "http://localhost:8000/healthz",
      reuseExistingServer: true,
      timeout: 60_000,
      env: { LLM_FAKE: "1" },
    },
    {
      command: "pnpm dev",
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
