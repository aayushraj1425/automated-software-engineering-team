"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  MANUAL_KINDS,
  type KnowledgeItem,
  type KnowledgeKind,
  type RepositoryOption,
} from "./types";

const KIND_COLORS: Record<KnowledgeKind, string> = {
  note: "bg-zinc-800 text-zinc-400",
  preference: "bg-sky-950 text-sky-300",
  decision: "bg-indigo-950 text-indigo-300",
  outcome: "bg-emerald-950 text-emerald-300",
};

/** One repository's long-term memory: browse, search, add, and delete it. */
export function KnowledgePanel() {
  const [repositories, setRepositories] = useState<RepositoryOption[]>([]);
  const [repositoryId, setRepositoryId] = useState<string | null>(null);
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState(false);
  const [kind, setKind] = useState<KnowledgeKind>("note");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const res = await fetch("/api/repositories");
      if (!res.ok) return;
      const repos: RepositoryOption[] = await res.json();
      setRepositories(repos);
      setRepositoryId((current) => current ?? repos[0]?.id ?? null);
    })();
  }, []);

  const refresh = useCallback(
    async (q?: string) => {
      if (!repositoryId) return;
      const params = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
      const res = await fetch(`/api/repositories/${repositoryId}/knowledge${params}`);
      if (res.ok) {
        setItems(await res.json());
        setSearched(Boolean(q?.trim()));
      }
    },
    [repositoryId],
  );

  useEffect(() => {
    setQuery("");
    void refresh();
  }, [refresh]);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    await refresh(query);
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!repositoryId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/repositories/${repositoryId}/knowledge`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind, title, content }),
      });
      if (!res.ok) throw new Error(`Could not save the memory (${res.status})`);
      setTitle("");
      setContent("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!repositoryId) return;
    const res = await fetch(`/api/repositories/${repositoryId}/knowledge/${id}`, {
      method: "DELETE",
    });
    setError(res.ok ? null : `Could not delete the memory (${res.status})`);
    await refresh(searched ? query : undefined);
  }

  const inputClasses =
    "w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500";

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <section className="space-y-3">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-zinc-300">Repository</h2>
          <select
            value={repositoryId ?? ""}
            onChange={(e) => setRepositoryId(e.target.value || null)}
            className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs outline-none focus:border-zinc-500"
          >
            {repositories.length === 0 && <option value="">No repositories connected</option>}
            {repositories.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.url}
              </option>
            ))}
          </select>
        </div>
        <p className="text-xs text-zinc-500">
          Decisions and outcomes are remembered automatically as runs finish; notes and
          preferences are written here. Planning recalls the most relevant memories.
        </p>
      </section>

      {repositoryId && (
        <form onSubmit={(e) => void search(e)} className="flex gap-3">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search the memory, e.g. why did we reject the caching plan?"
            className={inputClasses}
          />
          <button
            type="submit"
            className="shrink-0 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900"
          >
            Search
          </button>
          {searched && (
            <button
              type="button"
              onClick={() => {
                setQuery("");
                void refresh();
              }}
              className="shrink-0 rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-300"
            >
              Clear
            </button>
          )}
        </form>
      )}

      {repositoryId && (
        <form onSubmit={(e) => void add(e)} className="space-y-3">
          <h2 className="text-sm font-semibold text-zinc-300">Remember something</h2>
          <div className="flex gap-3">
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as KnowledgeKind)}
              className="shrink-0 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs outline-none focus:border-zinc-500"
            >
              {MANUAL_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="A short title, e.g. Deploys happen on Fridays"
              required
              maxLength={256}
              className={inputClasses}
            />
          </div>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="The memory itself — a meeting note, a team preference, a lesson learned"
            required
            rows={3}
            maxLength={4000}
            className={inputClasses}
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-zinc-100 px-4 py-1.5 text-sm font-medium text-zinc-900 disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save"}
          </button>
          {error && <p className="text-sm text-red-400">{error}</p>}
        </form>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">
          {searched ? "Most relevant memories" : "Memory"}
        </h2>
        {repositoryId && items.length === 0 && (
          <p className="text-sm text-zinc-500">
            {searched
              ? "Nothing in the memory matches that."
              : "Nothing remembered yet. Finish a run, or save the first note above."}
          </p>
        )}
        {items.map((item) => (
          <div key={item.id} className="space-y-2 rounded-md border border-zinc-800 p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm text-zinc-200">{item.title}</p>
              <button
                type="button"
                onClick={() => void remove(item.id)}
                className="shrink-0 text-xs text-zinc-600 hover:text-red-400"
                title="Delete this memory"
              >
                delete
              </button>
            </div>
            <p className="whitespace-pre-wrap text-xs text-zinc-400">{item.content}</p>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span
                className={`inline-block rounded-full px-2 py-0.5 font-medium ${KIND_COLORS[item.kind]}`}
              >
                {item.kind}
              </span>
              {item.source_run_id && (
                <Link
                  href={`/runs/${item.source_run_id}`}
                  className="text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
                >
                  from a run
                </Link>
              )}
              {item.score !== null && (
                <span className="text-zinc-500">relevance {item.score.toFixed(2)}</span>
              )}
              <span className="text-zinc-600">
                {new Date(item.created_at).toLocaleString()}
              </span>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
