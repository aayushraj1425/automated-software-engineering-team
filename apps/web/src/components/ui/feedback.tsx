import type { HTMLAttributes } from "react";

/** A bordered surface — the card look repeated across the pages, in one place. */
export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`rounded-md border border-zinc-800 ${className}`} {...props} />;
}

/** A spinning ring for inline "loading" states. */
export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-zinc-700 border-t-zinc-300 ${className}`}
    />
  );
}

/** A friendly placeholder for "there's nothing here yet", instead of a blank area. */
export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-md border border-dashed border-zinc-800 px-6 py-10 text-center">
      <p className="text-sm text-zinc-400">{title}</p>
      {hint && <p className="text-xs text-zinc-600">{hint}</p>}
    </div>
  );
}

/** An inline "that action failed" message. role="alert" so assistive tech
 * announces it the moment it appears, rather than the text showing silently.
 * Renders nothing when there's no message, so call sites drop the `error && …`
 * guard and just pass the (possibly null) message. */
export function FormError({
  message,
  className = "",
}: {
  message?: string | null;
  className?: string;
}) {
  if (!message) return null;
  return (
    <p role="alert" className={`text-sm text-red-400 ${className}`}>
      {message}
    </p>
  );
}

/** A pulsing block to hold layout while data loads, so pages don't flash blank. */
export function Skeleton({ className = "" }: { className?: string }) {
  // The `skeleton` marker lets globals.css pause just this decorative pulse
  // under prefers-reduced-motion, without touching the streaming cursor and the
  // "Live" dot, which share Tailwind's animate-pulse but are meaningful motion.
  return <div className={`skeleton animate-pulse rounded-md bg-zinc-900 ${className}`} />;
}
