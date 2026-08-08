import Link from "next/link";

/** The 404 page Next renders for an unknown URL or a notFound() call, so a
 * mistyped or stale link lands on a friendly page instead of a bare default. */
export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="space-y-1">
        <h1 className="text-lg font-semibold tracking-tight">Page not found</h1>
        <p className="max-w-sm text-sm text-zinc-400">
          The page you’re looking for doesn’t exist or may have moved.
        </p>
      </div>
      <Link
        href="/"
        className="inline-flex items-center justify-center rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 transition-colors hover:bg-white"
      >
        Back to app
      </Link>
    </main>
  );
}
