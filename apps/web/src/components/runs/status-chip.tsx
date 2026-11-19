const COLORS: Record<string, string> = {
  queued: "bg-zinc-800 text-zinc-300",
  planning: "bg-sky-950 text-sky-300",
  awaiting_approval: "bg-violet-950 text-violet-300",
  awaiting_deploy_approval: "bg-fuchsia-950 text-fuchsia-300",
  deploying: "bg-cyan-950 text-cyan-300",
  executing: "bg-amber-950 text-amber-300",
  reviewing: "bg-violet-950 text-violet-300",
  completed: "bg-emerald-950 text-emerald-300",
  done: "bg-emerald-950 text-emerald-300",
  failed: "bg-red-950 text-red-300",
  cancelled: "bg-zinc-800 text-zinc-400",
  pending: "bg-zinc-800 text-zinc-300",
  blocked: "bg-zinc-800 text-zinc-400",
  in_progress: "bg-amber-950 text-amber-300",
  skipped: "bg-zinc-800 text-zinc-400",
  // Work-item states (planning board): proposed is tentative, ready is a go.
  proposed: "bg-blue-950 text-blue-300",
  ready: "bg-teal-950 text-teal-300",
  connected: "bg-zinc-800 text-zinc-300",
  indexing: "bg-amber-950 text-amber-300",
  indexed: "bg-emerald-950 text-emerald-300",
  index_failed: "bg-red-950 text-red-300",
};

export function StatusChip({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        COLORS[status] ?? "bg-zinc-800 text-zinc-300"
      }`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
