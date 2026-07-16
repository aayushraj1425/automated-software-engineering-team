"use client";

import { useState } from "react";

import { authClient } from "@/lib/auth-client";
import type { SignInProvider } from "@/lib/sign-in-providers";

/** "Continue with …" buttons for every provider the server has configured.
 * Social sign-in doubles as sign-up: better-auth creates the account on the
 * first OAuth round-trip. Renders nothing when no provider is configured. */
export function SocialSignIn({ providers }: { providers: SignInProvider[] }) {
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  if (providers.length === 0) {
    return null;
  }

  async function continueWith(provider: SignInProvider["id"]) {
    setError(null);
    setPendingId(provider);
    const { error } = await authClient.signIn.social({ provider, callbackURL: "/chat" });
    // On success the browser navigates away; reaching here means it failed.
    setPendingId(null);
    if (error) {
      setError(error.message ?? `Could not start ${provider} sign-in`);
    }
  }

  return (
    <div className="mt-6 space-y-2">
      {providers.map((provider) => (
        <button
          key={provider.id}
          type="button"
          disabled={pendingId !== null}
          onClick={() => continueWith(provider.id)}
          className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 hover:border-zinc-400 disabled:opacity-50"
        >
          {pendingId === provider.id ? "Redirecting…" : `Continue with ${provider.label}`}
        </button>
      ))}
      {error && <p className="text-sm text-red-400">{error}</p>}
      <div className="flex items-center gap-3 pt-2 text-xs text-zinc-500">
        <div className="h-px flex-1 bg-zinc-800" />
        or use email
        <div className="h-px flex-1 bg-zinc-800" />
      </div>
    </div>
  );
}
