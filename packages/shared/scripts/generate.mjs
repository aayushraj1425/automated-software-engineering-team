// Regenerate TypeScript types for the engine API:
//   1. Export the OpenAPI spec straight from the FastAPI app (no server needed)
//   2. Run openapi-typescript over it
// Usage: pnpm --filter @asep/shared generate   (or `pnpm generate` at the root)

import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const pkg = path.resolve(here, "..");
const engineDir = path.resolve(pkg, "../../apps/engine");
const isWindows = process.platform === "win32";

const spec = execFileSync("uv", ["run", "python", "-m", "engine.openapi_export"], {
  cwd: engineDir,
  encoding: "utf8",
  shell: isWindows,
});
writeFileSync(path.join(pkg, "openapi.json"), spec);

execFileSync("npx", ["openapi-typescript", "openapi.json", "-o", "src/engine-api.d.ts"], {
  cwd: pkg,
  stdio: "inherit",
  shell: isWindows,
});

console.log("Generated packages/shared/src/engine-api.d.ts");
