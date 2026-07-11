"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { StatusChip } from "@/components/runs/status-chip";
import {
  ESTIMATES,
  KINDS,
  PRIORITIES,
  STATUSES,
  type Estimate,
  type PlanInsights,
  type Priority,
  type RepositoryOption,
  type WorkItem,
  type WorkItemKind,
  type WorkItemStatus,
} from "./types";

const PRIORITY_COLORS: Record<Priority, string> = {
  low: "bg-zinc-800 text-zinc-400",
  medium: "bg-sky-950 text-sky-300",
  high: "bg-amber-950 text-amber-300",
  critical: "bg-red-950 text-red-300",
};

/** The durable backlog for one repository: plan, size, order, and track work. */
export function PlanningBoard() {
  const [repositories, setRepositories] = useState<RepositoryOption[]>([]);
  const [repositoryId, setRepositoryId] = useState<string | null>(null);
  const [items, setItems] = useState<WorkItem[]>([]);
  const [title, setTitle] = useState("");
  const [milestone, setMilestone] = useState("");
  const [kind, setKind] = useState<WorkItemKind>("feature");
  const [priority, setPriority] = useState<Priority>("medium");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [goal, setGoal] = useState("");
  const [generating, setGenerating] = useState(false);
  const [insights, setInsights] = useState<PlanInsights | null>(null);
  const draggingId = useRef<string | null>(null);

  useEffect(() => {
    void (async () => {
      const res = await fetch("/api/repositories");
      if (!res.ok) return;
      const repos: RepositoryOption[] = await res.json();
      setRepositories(repos);
      setRepositoryId((current) => current ?? repos[0]?.id ?? null);
    })();
  }, []);

  const refresh = useCallback(async () => {
    if (!repositoryId) return;
    const [itemsRes, insightsRes] = await Promise.all([
      fetch(`/api/repositories/${repositoryId}/work-items`),
      fetch(`/api/repositories/${repositoryId}/work-items/insights`),
    ]);
    if (itemsRes.ok) setItems(await itemsRes.json());
    if (insightsRes.ok) setInsights(await insightsRes.json());
  }, [repositoryId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!repositoryId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/repositories/${repositoryId}/work-items`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title,
          kind,
          priority,
          milestone: milestone.trim() || null,
        }),
      });
      if (!res.ok) throw new Error(`Could not add the work item (${res.status})`);
      setTitle("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function generate(e: React.FormEvent) {
    e.preventDefault();
    if (!repositoryId) return;
    setGenerating(true);
    setError(null);
    try {
      const res = await fetch(`/api/repositories/${repositoryId}/roadmap`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ goal }),
      });
      if (!res.ok) throw new Error(`Could not generate a roadmap (${res.status})`);
      setGoal("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setGenerating(false);
    }
  }

  async function patch(id: string, changes: Partial<WorkItem>) {
    if (!repositoryId) return;
    await fetch(`/api/repositories/${repositoryId}/work-items/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(changes),
    });
    await refresh();
  }

  async function persistOrder(ordered: WorkItem[]) {
    if (!repositoryId) return;
    await fetch(`/api/repositories/${repositoryId}/work-items/reorder`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ordered_ids: ordered.map((item) => item.id) }),
    });
  }

  function onDragOver(overId: string) {
    const from = draggingId.current;
    if (!from || from === overId) return;
    setItems((current) => {
      const fromIndex = current.findIndex((item) => item.id === from);
      const toIndex = current.findIndex((item) => item.id === overId);
      if (fromIndex === -1 || toIndex === -1) return current;
      const next = [...current];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
  }

  function onDragEnd() {
    draggingId.current = null;
    void persistOrder(items);
  }

  const selectClasses =
    "rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs outline-none focus:border-zinc-500";

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <section className="space-y-3">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-zinc-300">Repository</h2>
          <select
            value={repositoryId ?? ""}
            onChange={(e) => setRepositoryId(e.target.value || null)}
            className={selectClasses}
          >
            {repositories.length === 0 && <option value="">No repositories connected</option>}
            {repositories.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.url}
              </option>
            ))}
          </select>
        </div>
      </section>

      {repositoryId && (
        <form onSubmit={(e) => void generate(e)} className="space-y-3">
          <h2 className="text-sm font-semibold text-zinc-300">
            Generate a roadmap{" "}
            <span className="font-normal text-zinc-500">
              — the Scrum Master turns a goal into work items
            </span>
          </h2>
          <div className="flex gap-3">
            <input
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="A one-line goal, e.g. Let users reset their password by email"
              required
              minLength={3}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
            />
            <button
              type="submit"
              disabled={generating}
              className="shrink-0 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
            >
              {generating ? "Planning…" : "Generate"}
            </button>
          </div>
        </form>
      )}

      {repositoryId && (
        <form onSubmit={(e) => void create(e)} className="space-y-3">
          <h2 className="text-sm font-semibold text-zinc-300">Add a work item</h2>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="What needs doing, e.g. Add password reset"
            required
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as WorkItemKind)}
              className={selectClasses}
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority)}
              className={selectClasses}
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p} priority
                </option>
              ))}
            </select>
            <input
              value={milestone}
              onChange={(e) => setMilestone(e.target.value)}
              placeholder="Milestone (optional)"
              className="flex-1 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs outline-none focus:border-zinc-500"
            />
            <button
              type="submit"
              disabled={busy}
              className="shrink-0 rounded-md bg-zinc-100 px-4 py-1.5 text-sm font-medium text-zinc-900 disabled:opacity-50"
            >
              {busy ? "Adding…" : "Add"}
            </button>
          </div>
          {error && <p className="text-sm text-red-400">{error}</p>}
        </form>
      )}

      {insights && (insights.recommended || insights.blocked.length > 0) && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-zinc-300">Plan health</h2>
          {insights.recommended && (
            <p className="rounded-md border border-emerald-900 bg-emerald-950/40 px-4 py-3 text-sm text-emerald-300">
              Up next: <span className="font-medium">{insights.recommended.title}</span>
              <span className="ml-2 text-xs text-emerald-500">
                {insights.recommended.priority} priority
                {insights.recommended.estimate ? ` · ${insights.recommended.estimate}` : ""}
              </span>
            </p>
          )}
          {insights.blocked.map((entry) => (
            <p
              key={entry.item_id}
              className="rounded-md border border-amber-900 bg-amber-950/40 px-4 py-3 text-sm text-amber-300"
            >
              Blocked: <span className="font-medium">{entry.title}</span>
              <span className="ml-2 text-xs text-amber-500">
                waiting on {entry.waiting_on.length} unfinished dependenc
                {entry.waiting_on.length === 1 ? "y" : "ies"}
              </span>
            </p>
          ))}
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Backlog</h2>
        {repositoryId && items.length === 0 && (
          <p className="text-sm text-zinc-500">
            Nothing planned yet. Add the first work item above.
          </p>
        )}
        {items.map((item) => (
          <div
            key={item.id}
            draggable
            onDragStart={() => (draggingId.current = item.id)}
            onDragOver={(e) => {
              e.preventDefault();
              onDragOver(item.id);
            }}
            onDragEnd={onDragEnd}
            className="cursor-grab space-y-2 rounded-md border border-zinc-800 p-4 hover:bg-zinc-900 active:cursor-grabbing"
          >
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm text-zinc-200">{item.title}</p>
              <StatusChip status={item.status} />
            </div>
            {item.rationale && <p className="text-xs text-zinc-500">{item.rationale}</p>}
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge className="bg-zinc-800 text-zinc-400">{item.kind}</Badge>
              <Badge className={PRIORITY_COLORS[item.priority]}>{item.priority}</Badge>
              {insights?.blocked.some((entry) => entry.item_id === item.id) && (
                <Badge className="bg-amber-950 text-amber-300">waiting on a dependency</Badge>
              )}
              {item.estimate && (
                <Badge className="bg-zinc-800 text-zinc-300">{item.estimate}</Badge>
              )}
              {item.milestone && (
                <Badge className="bg-indigo-950 text-indigo-300">{item.milestone}</Badge>
              )}
              {item.depends_on.length > 0 && (
                <Badge className="bg-zinc-800 text-zinc-400">
                  {item.depends_on.length} dependenc{item.depends_on.length === 1 ? "y" : "ies"}
                </Badge>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <label className="text-xs text-zinc-500">
                status{" "}
                <select
                  value={item.status}
                  onChange={(e) =>
                    void patch(item.id, { status: e.target.value as WorkItemStatus })
                  }
                  className={selectClasses}
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s.replace("_", " ")}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-zinc-500">
                estimate{" "}
                <select
                  value={item.estimate ?? ""}
                  onChange={(e) =>
                    void patch(item.id, {
                      estimate: (e.target.value || null) as Estimate | null,
                    })
                  }
                  className={selectClasses}
                >
                  <option value="">—</option>
                  {ESTIMATES.map((es) => (
                    <option key={es} value={es}>
                      {es}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}

function Badge({ children, className }: { children: React.ReactNode; className: string }) {
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 font-medium ${className}`}>
      {children}
    </span>
  );
}
