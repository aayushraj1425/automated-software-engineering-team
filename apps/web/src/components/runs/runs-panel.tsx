"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { relativeTime } from "@/lib/relative-time";

import { Button } from "../ui/button";
import { Card, EmptyState, FormError, Skeleton, Spinner } from "../ui/feedback";
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
    <Card className="px-4 py-3">
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
      <p className="text-xs text-zinc-500">{label}</p>
    </Card>
  );
}

export function RunsPanel() {
  const router = useRouter();
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [stats, setStats] = useState<RunStats | null>(null);
  const [filter, setFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [request, setRequest] = useState("");
  const [previewMode, setPreviewMode] = useState("infer");
  const [chartPath, setChartPath] = useState("deploy/helm");
  const [valuesFile, setValuesFile] = useState("");
  const [image, setImage] = useState("");
  const [ttlHours, setTtlHours] = useState(24);
  const [smokePaths, setSmokePaths] = useState("/healthz");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(true);

  // Stats once on mount; the run list re-fetches when the status filter changes.
  useEffect(() => {
    void (async () => {
      const res = await fetch("/api/runs/stats");
      if (res.ok) setStats(await res.json());
    })();
  }, []);

  // Typing shouldn't fire a request per keystroke — settle for 300ms first.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    // Discard a superseded response: if the filter/search changes again before
    // this fetch resolves, `ignore` stops a slow earlier reply from overwriting
    // the newer results.
    let ignore = false;
    void (async () => {
      const params = new URLSearchParams();
      if (filter) params.set("status", filter);
      if (debouncedSearch) params.set("q", debouncedSearch);
      const query = params.toString() ? `?${params}` : "";
      try {
        const res = await fetch(`/api/runs${query}`);
        if (!ignore && res.ok) setRuns(await res.json());
      } finally {
        if (!ignore) setLoadingRuns(false);
      }
    })();
    return () => {
      ignore = true;
    };
  }, [filter, debouncedSearch]);

  async function startRun(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/runs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          request,
          repository_url: repositoryUrl,
          ...(previewMode !== "infer" && { preview_requested: previewMode === "request" }),
          ...(previewMode === "request" && {
            preview_options: {
              chart_path: chartPath.trim(),
              values_file: valuesFile.trim() || null,
              image: image.trim() || null,
              ttl_hours: ttlHours,
              smoke_paths: smokePaths
                .split(",")
                .map((path) => path.trim())
                .filter(Boolean),
            },
          }),
        }),
      });
      if (!res.ok) {
        const failure = await res.json().catch(() => null);
        throw new Error(
          typeof failure?.detail === "string"
            ? failure.detail
            : `Could not start the run (${res.status})`,
        );
      }
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
          aria-label="Repository URL"
          placeholder="Repository URL, e.g. https://github.com/you/your-repo"
          required
          className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
        />
        <textarea
          value={request}
          onChange={(e) => setRequest(e.target.value)}
          aria-label="What you want built"
          placeholder="Describe the feature you want, e.g. Add a /status endpoint that returns the app version"
          required
          rows={3}
          className="w-full resize-none rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
        />
        <label className="block space-y-1 text-xs text-zinc-400">
          <span>Preview deployment</span>
          <select
            value={previewMode}
            onChange={(e) => setPreviewMode(e.target.value)}
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
          >
            <option value="infer">Infer from the request</option>
            <option value="off">Do not deploy</option>
            <option value="request">Request a preview</option>
          </select>
        </label>
        {previewMode === "request" && (
          <fieldset className="space-y-3 rounded-md border border-zinc-800 p-3">
            <legend className="px-1 text-xs text-zinc-400">Preview settings</legend>
            <p className="text-xs text-zinc-500">
              Uses your organization&apos;s preview cluster and requires a second approval. Publish
              the image first, or use the image already set in your chart.
            </p>
            {[
              { label: "Helm chart path", value: chartPath, set: setChartPath, required: true },
              { label: "Values file (optional)", value: valuesFile, set: setValuesFile },
              { label: "Published image (optional)", value: image, set: setImage },
              {
                label: "Smoke paths (comma separated)",
                value: smokePaths,
                set: setSmokePaths,
                required: true,
              },
            ].map(({ label, value, set, required }) => (
              <label key={label} className="block space-y-1 text-xs text-zinc-400">
                <span>{label}</span>
                <input
                  value={value}
                  onChange={(e) => set(e.target.value)}
                  required={required}
                  className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
                />
              </label>
            ))}
            <label className="block space-y-1 text-xs text-zinc-400">
              <span>Lifetime in hours</span>
              <input
                type="number"
                min={1}
                max={168}
                required
                value={ttlHours}
                onChange={(e) => setTtlHours(Number(e.target.value))}
                className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
              />
            </label>
          </fieldset>
        )}
        <FormError message={error} />
        <Button type="submit" disabled={busy}>
          {busy && <Spinner className="h-3.5 w-3.5" />}
          {busy ? "Starting…" : "Start run"}
        </Button>
      </form>

      {stats && stats.total > 0 && (
        <section className="grid grid-cols-3 gap-3">
          <Stat label="Runs" value={String(stats.total)} />
          <Stat
            label="Success rate"
            value={stats.success_rate === null ? "—" : `${Math.round(stats.success_rate * 100)}%`}
          />
          <Stat label="Total spend" value={`$${stats.total_cost_usd.toFixed(2)}`} />
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Previous runs</h2>
        {stats && stats.total > 0 && (
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search runs"
            placeholder="Search runs by what you asked for…"
            className="w-full rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
        )}
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
        {loadingRuns && runs.length === 0 ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-[52px] w-full" />
            ))}
          </div>
        ) : runs.length === 0 ? (
          <EmptyState
            title={
              debouncedSearch
                ? "No runs match your search."
                : filter
                  ? "No runs with this status."
                  : "No runs yet."
            }
            hint={
              !debouncedSearch && !filter
                ? "Describe a feature above to watch the agent team build it."
                : undefined
            }
          />
        ) : (
          runs.map((run) => (
            <button
              key={run.id}
              onClick={() => router.push(`/runs/${run.id}`)}
              className="flex w-full items-center justify-between gap-3 rounded-md border border-zinc-800 px-4 py-3 text-left hover:bg-zinc-900"
            >
              <span className="truncate text-sm">{run.request}</span>
              <span className="flex shrink-0 items-center gap-3">
                <span className="text-xs text-zinc-600">
                  {relativeTime(run.finished_at ?? run.started_at ?? run.created_at)}
                </span>
                <StatusChip status={run.status} />
              </span>
            </button>
          ))
        )}
      </section>
    </div>
  );
}
