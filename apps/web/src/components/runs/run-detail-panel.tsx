"use client";

import { useEffect, useRef, useState } from "react";

import { agentName, describeEvent } from "./event-text";
import { StatusChip } from "./status-chip";
import { FINISHED_STATUSES, type RunDetail, type RunEvent } from "./types";

const POLL_MS = 1500;

/** Watches one run: polls the run (task board) and its events (timeline)
 * until the run finishes. */
export function RunDetailPanel({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const cursorRef = useRef(0);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      const [runRes, eventsRes] = await Promise.all([
        fetch(`/api/runs/${runId}`),
        fetch(`/api/runs/${runId}/events?after=${cursorRef.current}`),
      ]);
      if (stopped) return;
      let finished = false;
      if (runRes.ok) {
        const detail: RunDetail = await runRes.json();
        setRun(detail);
        finished = FINISHED_STATUSES.has(detail.status);
      }
      if (eventsRes.ok) {
        const fresh: RunEvent[] = await eventsRes.json();
        if (fresh.length > 0) {
          cursorRef.current = fresh[fresh.length - 1].id;
          setEvents((prev) => [...prev, ...fresh]);
        }
      }
      if (!stopped && !finished) timer = setTimeout(() => void poll(), POLL_MS);
    }

    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [runId]);

  if (!run) {
    return <p className="p-6 text-sm text-zinc-500">Loading run…</p>;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <header className="space-y-2">
        <div className="flex items-center gap-3">
          <StatusChip status={run.status} />
          <span className="truncate text-xs text-zinc-500">{run.repository_url}</span>
        </div>
        <h1 className="text-lg font-semibold">{run.request}</h1>
        {run.error && <p className="text-sm text-red-400">{run.error}</p>}
        {run.plan?.summary && <p className="text-sm text-zinc-400">{run.plan.summary}</p>}
      </header>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Task board</h2>
        {run.tasks.length === 0 && (
          <p className="text-sm text-zinc-500">No tasks yet — the plan is being written.</p>
        )}
        {run.tasks.map((task) => (
          <div
            key={task.id}
            className="flex items-center justify-between gap-3 rounded-md border border-zinc-800 px-4 py-3"
          >
            <div className="min-w-0">
              <p className="truncate text-sm">
                {task.sequence}. {task.title}
              </p>
              <p className="text-xs text-zinc-500">{agentName(task.role)}</p>
            </div>
            <StatusChip status={task.status} />
          </div>
        ))}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Timeline</h2>
        <ol className="space-y-1">
          {events.map((event) => (
            <li key={event.id} className="flex gap-3 text-sm">
              <span className="shrink-0 tabular-nums text-xs leading-6 text-zinc-600">
                {new Date(event.created_at).toLocaleTimeString()}
              </span>
              <span className="text-zinc-300">{describeEvent(event)}</span>
            </li>
          ))}
        </ol>
        {!FINISHED_STATUSES.has(run.status) && (
          <p className="animate-pulse text-xs text-zinc-500">Watching for updates…</p>
        )}
      </section>
    </div>
  );
}
