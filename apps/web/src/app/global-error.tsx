"use client";

import { useEffect } from "react";

/** The last-resort boundary: it catches errors thrown by the root layout
 * itself, which the segment-level error.tsx cannot. Because it replaces the
 * whole document when the layout is what failed, it must render its own
 * <html>/<body> and carry the base colors inline rather than rely on the
 * layout. */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body className="min-h-screen bg-zinc-950 font-sans text-zinc-100 antialiased">
        <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
          <div className="space-y-1">
            <h1 className="text-lg font-semibold tracking-tight">Something went wrong</h1>
            <p className="max-w-sm text-sm text-zinc-400">
              The app hit an unexpected error. Reload to try again.
            </p>
            {error.digest && <p className="text-xs text-zinc-600">Reference: {error.digest}</p>}
          </div>
          <button
            type="button"
            onClick={reset}
            className="inline-flex items-center justify-center rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 transition-colors hover:bg-white"
          >
            Reload
          </button>
        </main>
      </body>
    </html>
  );
}
