"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { StatusChip } from "./status-chip";
import type { RunSummary } from "./types";

type RunStats = {
  total: number;
  by_status: Record<string, number>;
  completed: number;
  failed: number;
  success_rate: number | null;
  total_cost_usd: number;
  total_tokens: number;
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-zinc-800 px-4 py-3">
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
      <p className="text-xs text-zinc-500">{label}</p>
    </div>
  );
}

export function RunsPanel() {
  const router = useRouter();
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [stats, setStats] = useState<RunStats | null>(null);
  const [filter, setFilter] = useState<string | null>(null);
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [request, setRequest] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stats once on mount; the run list re-fetches when the status filter changes.
  useEffect(() => {
    void (async () => {
      const res = await fetch("/api/runs/stats");
      if (res.ok) setStats(await res.json());
    })();
  }, []);

  useEffect(() => {
    void (async () => {
      const query = filter ? `?status=${encodeURIComponent(filter)}` : "";
      const res = await fetch(`/api/runs${query}`);
      if (res.ok) setRuns(await res.json());
    })();
  }, [filter]);

  async function startRun(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/runs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ request, repository_url: repositoryUrl }),
      });
      if (!res.ok) throw new Error(`Could not start the run (${res.status})`);
      const run: RunSummary = await res.json();
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <form onSubmit={(e) => void startRun(e)} className="space-y-3">
        <h2 className="text-sm font-semibold text-zinc-300">Start a new run</h2>
        <input
          value={repositoryUrl}
          onChange={(e) => setRepositoryUrl(e.target.value)}
          placeholder="Repository URL, e.g. https://github.com/you/your-repo"
          required
          className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
        />
        <textarea
          value={request}
          onChange={(e) => setRequest(e.target.value)}
          placeholder="Describe the feature you want, e.g. Add a /status endpoint that returns the app version"
          required
          rows={3}
          className="w-full resize-none rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
        />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
        >
          {busy ? "Starting…" : "Start run"}
        </button>
      </form>

      {stats && stats.total > 0 && (
        <section className="grid grid-cols-3 gap-3">
          <Stat label="Runs" value={String(stats.total)} />
          <Stat
            label="Success rate"
            value={
              stats.success_rate === null ? "—" : `${Math.round(stats.success_rate * 100)}%`
            }
          />
          <Stat label="Total spend" value={`$${stats.total_cost_usd.toFixed(2)}`} />
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Previous runs</h2>
        {stats && stats.total > 0 && (
          <div className="flex flex-wrap gap-2">
            {[
              ["All", null] as const,
              ...Object.keys(stats.by_status)
                .sort()
                .map((s) => [`${s.replace(/_/g, " ")} (${stats.by_status[s]})`, s] as const),
            ].map(([label, value]) => (
              <button
                key={label}
                type="button"
                onClick={() => setFilter(value)}
                className={`rounded-full border px-3 py-1 text-xs ${
                  filter === value
                    ? "border-zinc-300 bg-zinc-100 text-zinc-900"
                    : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
        {runs.length === 0 && (
          <p className="text-sm text-zinc-500">
            {filter ? "No runs with this status." : "No runs yet."}
          </p>
        )}
        {runs.map((run) => (
          <button
            key={run.id}
            onClick={() => router.push(`/runs/${run.id}`)}
            className="flex w-full items-center justify-between gap-3 rounded-md border border-zinc-800 px-4 py-3 text-left hover:bg-zinc-900"
          >
            <span className="truncate text-sm">{run.request}</span>
            <StatusChip status={run.status} />
          </button>
        ))}
      </section>
    </div>
  );
}
