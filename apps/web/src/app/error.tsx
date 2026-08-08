"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

/** The app-wide error boundary. Next renders this in place of any page segment
 * whose render threw, instead of leaving a blank screen. `reset` re-renders the
 * failed segment, so a transient failure (a flaky fetch) can recover without a
 * full reload. Must be a client component — error boundaries run on the client. */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surfaced to the browser console (and any error-reporting hook) so a
    // failure is diagnosable, not silent.
    console.error(error);
  }, [error]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="space-y-1">
        <h1 className="text-lg font-semibold tracking-tight">Something went wrong</h1>
        <p className="max-w-sm text-sm text-zinc-400">
          An unexpected error interrupted this page. You can try again, or go back to the start.
        </p>
        {error.digest && <p className="text-xs text-zinc-600">Reference: {error.digest}</p>}
      </div>
      <div className="flex gap-2">
        <Button onClick={reset}>Try again</Button>
        <Button variant="secondary" onClick={() => location.assign("/")}>
          Go home
        </Button>
      </div>
    </main>
  );
}
