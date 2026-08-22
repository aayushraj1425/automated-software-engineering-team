"use client";

import { useCallback, useEffect, useState } from "react";

import { StatusChip } from "@/components/runs/status-chip";
import { relativeTime } from "@/lib/relative-time";
import { Button } from "../ui/button";
import { EmptyState, FormError, Skeleton, Spinner } from "../ui/feedback";
import { DependencyGraphView } from "./dependency-graph";
import type { DependencyGraph, RepositorySummary, SearchHit } from "./types";

const POLL_MS = 2000;

/** Connect repositories, build their search index, and ask it questions. */
export function RepositoriesPanel() {
  const [repositories, setRepositories] = useState<RepositorySummary[]>([]);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [graph, setGraph] = useState<DependencyGraph | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [loadingRepos, setLoadingRepos] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/repositories");
      if (res.ok) setRepositories(await res.json());
    } finally {
      setLoadingRepos(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // While anything is indexing, poll so status and chunk counts update live.
  useEffect(() => {
    if (!repositories.some((repo) => repo.status === "indexing")) return;
    const timer = setTimeout(() => void refresh(), POLL_MS);
    return () => clearTimeout(timer);
  }, [repositories, refresh]);

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/repositories", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!res.ok) throw new Error(`Could not connect the repository (${res.status})`);
      setUrl("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function startIndexing(id: string) {
    const res = await fetch(`/api/repositories/${id}/index`, { method: "POST" });
    if (res.ok) await refresh();
  }

  async function disconnect(id: string) {
    if (
      !window.confirm(
        "Disconnect this repository? Its index, work items, knowledge, and documents " +
          "are removed. Run history is kept.",
      )
    ) {
      return;
    }
    setError(null);
    const res = await fetch(`/api/repositories/${id}`, { method: "DELETE" });
    if (!res.ok && res.status !== 204) {
      const detail = await res.json().catch(() => null);
      setError(detail?.detail ?? `Could not disconnect (${res.status})`);
      return;
    }
    if (selectedId === id) setSelectedId(null);
    await refresh();
  }

  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    setSearching(true);
    setHits(null);
    try {
      const res = await fetch(
        `/api/repositories/${selectedId}/search?q=${encodeURIComponent(query)}`,
      );
      if (res.ok) setHits(await res.json());
    } finally {
      setSearching(false);
    }
  }

  function selectRepository(id: string) {
    setSelectedId(id);
    setHits(null);
    setGraph(null); // the graph belongs to the previously selected repository
  }

  async function toggleGraph() {
    if (graph) {
      setGraph(null);
      return;
    }
    if (!selectedId) return;
    setGraphLoading(true);
    try {
      const res = await fetch(`/api/repositories/${selectedId}/graph`);
      if (res.ok) setGraph(await res.json());
    } finally {
      setGraphLoading(false);
    }
  }

  const selected = repositories.find((repo) => repo.id === selectedId);

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <form onSubmit={(e) => void connect(e)} className="space-y-3">
        <h2 className="text-sm font-semibold text-zinc-300">Connect a repository</h2>
        <div className="flex gap-3">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            aria-label="Repository URL"
            placeholder="Repository URL, e.g. https://github.com/you/your-repo"
            required
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
          <Button type="submit" disabled={busy} className="shrink-0">
            {busy && <Spinner className="h-3.5 w-3.5" />}
            {busy ? "Connecting…" : "Connect"}
          </Button>
        </div>
        <FormError message={error} />
      </form>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Your repositories</h2>
        {loadingRepos && repositories.length === 0 ? (
          <div className="space-y-2">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-[68px] w-full" />
            ))}
          </div>
        ) : repositories.length === 0 ? (
          <EmptyState
            title="Nothing connected yet."
            hint="Connect a repository above to index and search it."
          />
        ) : (
          repositories.map((repo) => (
            <div
              key={repo.id}
              onClick={() => selectRepository(repo.id)}
              className={`flex cursor-pointer items-center justify-between gap-3 rounded-md border px-4 py-3 ${
                repo.id === selectedId
                  ? "border-zinc-500 bg-zinc-900"
                  : "border-zinc-800 hover:bg-zinc-900"
              }`}
            >
              <div className="min-w-0">
                <p className="truncate text-sm">{repo.url}</p>
                <p className="text-xs text-zinc-500">
                  {repo.chunks > 0
                    ? `${repo.chunks.toLocaleString()} indexed pieces`
                    : "not indexed yet"}
                  {repo.chunks > 0 && repo.last_indexed_at && (
                    <> · indexed {relativeTime(repo.last_indexed_at)}</>
                  )}
                </p>
                {repo.status === "index_failed" && repo.status_detail && (
                  <p className="mt-1 truncate text-xs text-red-400" title={repo.status_detail}>
                    Indexing failed: {repo.status_detail}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <StatusChip status={repo.status} />
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    void startIndexing(repo.id);
                  }}
                  disabled={repo.status === "indexing"}
                >
                  {repo.status === "indexing"
                    ? "Indexing…"
                    : repo.chunks > 0
                      ? "Re-index"
                      : "Index"}
                </Button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    void disconnect(repo.id);
                  }}
                  title="Disconnect — run history is kept"
                  className="text-xs text-zinc-600 hover:text-red-400"
                >
                  disconnect
                </button>
              </div>
            </div>
          ))
        )}
      </section>

      {selected && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-zinc-300">
            Search <span className="font-normal text-zinc-500">{selected.url}</span>
          </h2>
          <form onSubmit={(e) => void search(e)} className="flex gap-3">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search the code"
              placeholder="Ask the code a question, e.g. where are items listed?"
              required
              minLength={2}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
            />
            <Button
              type="submit"
              disabled={searching || selected.chunks === 0}
              className="shrink-0"
            >
              {searching ? "Searching…" : "Search"}
            </Button>
          </form>
          {selected.chunks === 0 && (
            <p className="text-sm text-zinc-500">Index the repository first, then search.</p>
          )}
          {hits !== null && hits.length === 0 && (
            <p className="text-sm text-zinc-500">No matches.</p>
          )}
          {hits?.map((hit, index) => (
            <div key={index} className="space-y-2 rounded-md border border-zinc-800 p-4">
              <p className="flex items-baseline justify-between gap-3 text-xs">
                <span className="truncate font-medium text-zinc-300">
                  {hit.path}:{hit.start_line}–{hit.end_line}
                </span>
                <span className="shrink-0 text-zinc-500">
                  {hit.language} · score {hit.score.toFixed(2)}
                </span>
              </p>
              <pre className="overflow-x-auto text-xs leading-5 text-zinc-400">{hit.snippet}</pre>
            </div>
          ))}
        </section>
      )}

      {selected && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-300">Dependencies</h2>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void toggleGraph()}
              disabled={graphLoading || selected.chunks === 0}
            >
              {graphLoading ? "Loading…" : graph ? "Hide graph" : "Show graph"}
            </Button>
          </div>
          {selected.chunks === 0 && (
            <p className="text-sm text-zinc-500">Index the repository first to see its graph.</p>
          )}
          {graph && <DependencyGraphView graph={graph} />}
        </section>
      )}
    </div>
  );
}
