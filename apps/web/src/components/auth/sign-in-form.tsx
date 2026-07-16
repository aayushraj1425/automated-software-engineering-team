"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { SocialSignIn } from "@/components/auth/social-sign-in";
import { signIn } from "@/lib/auth-client";
import type { SignInProvider } from "@/lib/sign-in-providers";

export function SignInForm({ providers }: { providers: SignInProvider[] }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    const { error } = await signIn.email({ email, password });
    setPending(false);
    if (error) {
      setError(error.message ?? "Sign in failed");
      return;
    }
    router.push("/chat");
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-xl border border-zinc-800 bg-zinc-900 p-8">
        <h1 className="text-xl font-semibold">Sign in to ASEP</h1>
        <p className="mt-1 text-sm text-zinc-400">Your AI software engineering team.</p>
        <SocialSignIn providers={providers} />
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm text-zinc-300">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-400"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm text-zinc-300">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-400"
            />
          </div>
          {error && <p className="text-sm text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={pending}
            className="w-full rounded-md bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-900 hover:bg-white disabled:opacity-50"
          >
            {pending ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="mt-4 text-sm text-zinc-400">
          No account?{" "}
          <Link href="/sign-up" className="text-zinc-100 underline">
            Create one
          </Link>
        </p>
      </div>
    </main>
  );
}
