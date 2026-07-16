// Server-side only: which OAuth providers have credentials configured.
// The sign-in/sign-up pages pass this plain list to their client forms, so
// the client learns provider *names*, never secrets — and an unconfigured
// provider shows no dead button (docs/architecture/SIGN_IN_AND_ORGANIZATIONS.md).

import { env } from "@/lib/env";

export type SignInProvider = { id: "github" | "google" | "microsoft"; label: string };

export function configuredProviders(): SignInProvider[] {
  const providers: SignInProvider[] = [];
  if (env.GITHUB_CLIENT_ID && env.GITHUB_CLIENT_SECRET) {
    providers.push({ id: "github", label: "GitHub" });
  }
  if (env.GOOGLE_CLIENT_ID && env.GOOGLE_CLIENT_SECRET) {
    providers.push({ id: "google", label: "Google" });
  }
  if (env.MICROSOFT_CLIENT_ID && env.MICROSOFT_CLIENT_SECRET) {
    providers.push({ id: "microsoft", label: "Microsoft" });
  }
  return providers;
}
