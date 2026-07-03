// Server-side env access. The root .env is loaded by next.config.ts.
// The engine uses SQLAlchemy's `postgresql+psycopg://` scheme; node-postgres
// wants plain `postgresql://` — normalize here so one .env serves both.

function pgUrl(url: string): string {
  return url.replace("postgresql+psycopg://", "postgresql://");
}

export const env = {
  DATABASE_URL: pgUrl(process.env.DATABASE_URL ?? "postgresql://asep:asep@localhost:5433/asep"),
  BETTER_AUTH_SECRET: process.env.BETTER_AUTH_SECRET ?? "dev-only-secret-change-me-0000000000",
  BETTER_AUTH_URL: process.env.BETTER_AUTH_URL ?? "http://localhost:3000",
  ENGINE_URL: process.env.ENGINE_URL ?? "http://localhost:8000",
  ENGINE_SERVICE_SECRET:
    process.env.ENGINE_SERVICE_SECRET ?? "dev-only-service-secret-change-me-00",
  GITHUB_CLIENT_ID: process.env.GITHUB_CLIENT_ID,
  GITHUB_CLIENT_SECRET: process.env.GITHUB_CLIENT_SECRET,
  GOOGLE_CLIENT_ID: process.env.GOOGLE_CLIENT_ID,
  GOOGLE_CLIENT_SECRET: process.env.GOOGLE_CLIENT_SECRET,
  MICROSOFT_CLIENT_ID: process.env.MICROSOFT_CLIENT_ID,
  MICROSOFT_CLIENT_SECRET: process.env.MICROSOFT_CLIENT_SECRET,
};
