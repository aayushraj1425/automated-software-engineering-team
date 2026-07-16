"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { SocialSignIn } from "@/components/auth/social-sign-in";
import { signUp } from "@/lib/auth-client";
import type { SignInProvider } from "@/lib/sign-in-providers";

export function SignUpForm({ providers }: { providers: SignInProvider[] }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    const { error } = await signUp.email({ name, email, password });
    setPending(false);
    if (error) {
      setError(error.message ?? "Sign up failed");
      return;
    }
    router.push("/chat");
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-xl border border-zinc-800 bg-zinc-900 p-8">
        <h1 className="text-xl font-semibold">Create your ASEP account</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Sign up with a provider or use email + password.
        </p>
        <SocialSignIn providers={providers} />
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="name" className="block text-sm text-zinc-300">
              Name
            </label>
            <input
              id="name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-400"
            />
          </div>
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
              Password (8+ characters)
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
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
            {pending ? "Creating account…" : "Create account"}
          </button>
        </form>
        <p className="mt-4 text-sm text-zinc-400">
          Already registered?{" "}
          <Link href="/sign-in" className="text-zinc-100 underline">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
