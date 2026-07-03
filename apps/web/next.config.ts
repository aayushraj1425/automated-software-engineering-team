import path from "node:path";
import { config as loadEnv } from "dotenv";
import type { NextConfig } from "next";

// One .env at the repo root drives everything (see .env.example). All values
// here are server-side only; NEXT_PUBLIC_ vars would need a different path.
loadEnv({ path: path.resolve(process.cwd(), "../../.env") });

const nextConfig: NextConfig = {};

export default nextConfig;
