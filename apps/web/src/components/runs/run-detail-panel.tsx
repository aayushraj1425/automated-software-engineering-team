"use client";

import { useEffect, useRef, useState } from "react";

import { agentName, describeEvent } from "./event-text";
import { StatusChip } from "./status-chip";
import {
  FINISHED_STATUSES,
  type RunDetail,
  type RunEvent,
  type WorkspaceFile,
} from "./types";

const POLL_MS = 1500;

// The diff exists once the engineers have worked (and the workspace remains).
const DIFF_STATUSES = new Set(["reviewing", "completed", "failed"]);
// The workspace exists from planning onward (until a rejected run deletes it).
const FILE_STATUSES = new Set([
  "awaiting_approval",
  "executing",
  "reviewing",
  "completed",
  "failed",
]);

function diffLineClass(line: string): string {
  if (line.startsWith("+")) return "text-emerald-400";
  if (line.startsWith("-")) return "text-red-400";
  if (line.startsWith("@@")) return "text-sky-400";
  return "text-zinc-400";
}

/** Watches one run live: events stream in over SSE (each one nudges a
 * throttled task-board refresh); if the stream fails, falls back to the old
 * polling loop. Design note: docs/architecture/RUN_EVENT_STREAMING.md. */
export function RunDetailPanel({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [deciding, setDeciding] = useState(false);
  const [diff, setDiff] = useState<string | null>(null);
  const [files, setFiles] = useState<WorkspaceFile[] | null>(null);
  const [filesTruncated, setFilesTruncated] = useState(false);
  const [openPath, setOpenPath] = useState<string | null>(null);
  const [fileBody, setFileBody] = useState<{ content: string; truncated: boolean } | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [gitChanges, setGitChanges] = useState<{ path: string; code: string }[]>([]);
  const [commitMessage, setCommitMessage] = useState("");
  const [committing, setCommitting] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [editingPlan, setEditingPlan] = useState(false);
  const [planDrafts, setPlanDrafts] = useState<
    Record<string, { title: string; description: string; drop: boolean }>
  >({});
  const [savingPlan, setSavingPlan] = useState(false);
  const [planNote, setPlanNote] = useState<string | null>(null);
  const [workspaceNote, setWorkspaceNote] = useState<string | null>(null);
  const cursorRef = useRef(0);
  const diffRequestedRef = useRef(false);
  const filesRequestedRef = useRef(false);

  async function openFile(path: string) {
    setOpenPath(path);
    setFileBody(null);
    setDraft(null);
    setFileError(null);
    const res = await fetch(`/api/runs/${runId}/files/content?path=${encodeURIComponent(path)}`);
    if (res.ok) {
      const body = (await res.json()) as { content: string; truncated: boolean };
      setFileBody(body);
      setDraft(body.content);
    } else {
      setFileError(`Could not open ${path} (${res.status})`);
    }
  }

  async function refreshGitStatus() {
    const res = await fetch(`/api/runs/${runId}/git-status`);
    if (res.ok) setGitChanges(((await res.json()) as { changes: typeof gitChanges }).changes);
  }

  async function saveFile() {
    if (openPath === null || draft === null) return;
    setSaving(true);
    setWorkspaceNote(null);
    try {
      const res = await fetch(`/api/runs/${runId}/files/content`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ path: openPath, content: draft }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail ?? `Save failed (${res.status})`);
      }
      setFileBody((prev) => (prev ? { ...prev, content: draft } : prev));
      await refreshGitStatus();
      setWorkspaceNote("Saved.");
    } catch (err) {
      setWorkspaceNote(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function commitWorkspace() {
    if (!commitMessage.trim()) return;
    setCommitting(true);
    setWorkspaceNote(null);
    try {
      const res = await fetch(`/api/runs/${runId}/commit`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: commitMessage.trim() }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail ?? `Commit failed (${res.status})`);
      setCommitMessage("");
      setWorkspaceNote(`Committed ${body.sha}.`);
      await refreshGitStatus();
    } catch (err) {
      setWorkspaceNote(err instanceof Error ? err.message : "Commit failed");
    } finally {
      setCommitting(false);
    }
  }

  async function pushBranch() {
    setPushing(true);
    setWorkspaceNote(null);
    try {
      const res = await fetch(`/api/runs/${runId}/push`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail ?? `Push failed (${res.status})`);
      setWorkspaceNote(`Branch ${body.branch} pushed.`);
    } catch (err) {
      setWorkspaceNote(err instanceof Error ? err.message : "Push failed");
    } finally {
      setPushing(false);
    }
  }

  function startPlanEdit() {
    if (!run) return;
    setPlanDrafts(
      Object.fromEntries(
        run.tasks.map((task) => [
          task.id,
          { title: task.title, description: task.description ?? "", drop: false },
        ]),
      ),
    );
    setPlanNote(null);
    setEditingPlan(true);
  }

  async function savePlan() {
    if (!run) return;
    setSavingPlan(true);
    setPlanNote(null);
    try {
      const res = await fetch(`/api/runs/${runId}/plan`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          tasks: run.tasks.map((task) => {
            const draft = planDrafts[task.id];
            return {
              id: task.id,
              title: draft?.title ?? task.title,
              // "" clears the description; null would leave it unchanged.
              description: draft ? draft.description : null,
              drop: draft?.drop ?? false,
            };
          }),
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail ?? `Could not save the plan (${res.status})`);
      setEditingPlan(false);
      const refreshed = await fetch(`/api/runs/${runId}`);
      if (refreshed.ok) setRun(await refreshed.json());
    } catch (err) {
      setPlanNote(err instanceof Error ? err.message : "Could not save the plan");
    } finally {
      setSavingPlan(false);
    }
  }

  async function decide(approved: boolean) {
    setDeciding(true);
    try {
      const res = await fetch(`/api/runs/${runId}/decision`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ approved }),
      });
      if (res.ok) {
        const updated: RunDetail = await res.json();
        setRun((prev) => (prev ? { ...prev, status: updated.status } : prev));
      }
    } finally {
      setDeciding(false);
    }
  }

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;
    let source: EventSource | null = null;

    async function fetchRun(): Promise<boolean> {
      const res = await fetch(`/api/runs/${runId}`);
      if (!res.ok || stopped) return false;
      const detail: RunDetail = await res.json();
      setRun(detail);
      return FINISHED_STATUSES.has(detail.status);
    }

    // Events arrive in bursts; one board refresh shortly after the last one.
    function scheduleRunRefresh() {
      if (refreshTimer !== null) return;
      refreshTimer = setTimeout(() => {
        refreshTimer = null;
        void fetchRun();
      }, 300);
    }

    function startStream() {
      source = new EventSource(`/api/runs/${runId}/events/stream?after=${cursorRef.current}`);
      source.onmessage = (e: MessageEvent<string>) => {
        const event: RunEvent = JSON.parse(e.data);
        if (event.id > cursorRef.current) {
          // The id guard makes reconnect replays harmless.
          cursorRef.current = event.id;
          setEvents((prev) => [...prev, event]);
        }
        scheduleRunRefresh();
      };
      source.addEventListener("end", () => {
        source?.close();
        void fetchRun(); // the final status, PR link, and cost totals
      });
      source.onerror = () => {
        // EventSource retries transient drops itself; a closed source means
        // the stream is unreachable — fall back to polling.
        if (source?.readyState === EventSource.CLOSED && !stopped) {
          source = null;
          void poll();
        }
      };
    }

    async function poll() {
      const [finished, eventsRes] = await Promise.all([
        fetchRun(),
        fetch(`/api/runs/${runId}/events?after=${cursorRef.current}`),
      ]);
      if (stopped) return;
      if (eventsRes.ok) {
        const fresh: RunEvent[] = await eventsRes.json();
        if (fresh.length > 0) {
          cursorRef.current = fresh[fresh.length - 1].id;
          setEvents((prev) => [...prev, ...fresh]);
        }
      }
      if (!stopped && !finished) timer = setTimeout(() => void poll(), POLL_MS);
    }

    void fetchRun();
    startStream();
    return () => {
      stopped = true;
      clearTimeout(timer);
      if (refreshTimer !== null) clearTimeout(refreshTimer);
      source?.close();
    };
  }, [runId]);

  useEffect(() => {
    if (!run || diffRequestedRef.current || !DIFF_STATUSES.has(run.status)) return;
    diffRequestedRef.current = true;
    void (async () => {
      const res = await fetch(`/api/runs/${runId}/diff`);
      if (res.ok) setDiff(((await res.json()) as { diff: string }).diff);
    })();
  }, [run, runId]);

  useEffect(() => {
    if (!run || filesRequestedRef.current || !FILE_STATUSES.has(run.status)) return;
    filesRequestedRef.current = true;
    void (async () => {
      const res = await fetch(`/api/runs/${runId}/files`);
      if (!res.ok) return;
      const body = (await res.json()) as { files: WorkspaceFile[]; truncated: boolean };
      setFiles(body.files);
      setFilesTruncated(body.truncated);
      // On a finished run the workspace is editable — show its working tree.
      if (run.status === "completed" || run.status === "failed") {
        const statusRes = await fetch(`/api/runs/${runId}/git-status`);
        if (statusRes.ok) {
          setGitChanges(((await statusRes.json()) as { changes: typeof gitChanges }).changes);
        }
      }
    })();
  }, [run, runId]);

  if (!run) {
    return <p className="p-6 text-sm text-zinc-500">Loading run…</p>;
  }

  // A finished run's workspace is idle — safe for a human to edit and commit.
  const editable = run.status === "completed" || run.status === "failed";

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
        {run.total_input_tokens + run.total_output_tokens > 0 && (
          <p className="text-xs text-zinc-500">
            {run.total_input_tokens.toLocaleString()} tokens in ·{" "}
            {run.total_output_tokens.toLocaleString()} tokens out · $
            {run.total_cost_usd.toFixed(4)}
          </p>
        )}
        {run.pr_url && (
          <a
            href={run.pr_url}
            target="_blank"
            rel="noreferrer"
            className="inline-block rounded-md border border-emerald-800 px-3 py-1.5 text-sm text-emerald-300 hover:bg-emerald-950/40"
          >
            View the pull request ↗
          </a>
        )}
      </header>

      {run.status === "awaiting_approval" && (
        <section className="space-y-3 rounded-md border border-violet-900 bg-violet-950/30 p-4">
          <p className="text-sm text-zinc-200">
            The plan is ready. Nothing runs until you decide — a nearly-right plan can be
            edited below before approving.
          </p>
          <div className="flex gap-3">
            <button
              onClick={() => void decide(true)}
              disabled={deciding || editingPlan}
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              Approve plan
            </button>
            <button
              onClick={() => void decide(false)}
              disabled={deciding || editingPlan}
              className="rounded-md border border-red-800 px-4 py-2 text-sm font-medium text-red-300 disabled:opacity-50"
            >
              Reject
            </button>
            {editingPlan ? (
              <>
                <button
                  onClick={() => void savePlan()}
                  disabled={savingPlan}
                  className="rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
                >
                  {savingPlan ? "Saving…" : "Save plan"}
                </button>
                <button
                  onClick={() => setEditingPlan(false)}
                  disabled={savingPlan}
                  className="rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-300 disabled:opacity-50"
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                onClick={startPlanEdit}
                disabled={deciding}
                className="rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:border-zinc-400 disabled:opacity-50"
              >
                Edit plan
              </button>
            )}
          </div>
          {planNote && <p className="text-sm text-red-400">{planNote}</p>}
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Task board</h2>
        {run.tasks.length === 0 && (
          <p className="text-sm text-zinc-500">No tasks yet — the plan is being written.</p>
        )}
        {run.tasks.map((task) =>
          editingPlan ? (
            <div
              key={task.id}
              className={`space-y-2 rounded-md border px-4 py-3 ${
                planDrafts[task.id]?.drop ? "border-red-900 opacity-60" : "border-zinc-700"
              }`}
            >
              <div className="flex items-center gap-3">
                <span className="shrink-0 text-xs text-zinc-500">{task.sequence}.</span>
                <input
                  value={planDrafts[task.id]?.title ?? task.title}
                  onChange={(e) =>
                    setPlanDrafts((prev) => ({
                      ...prev,
                      [task.id]: { ...prev[task.id], title: e.target.value },
                    }))
                  }
                  disabled={planDrafts[task.id]?.drop}
                  className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm outline-none focus:border-zinc-500 disabled:line-through"
                />
                <span className="shrink-0 text-xs text-zinc-500">{agentName(task.role)}</span>
                <button
                  type="button"
                  onClick={() =>
                    setPlanDrafts((prev) => ({
                      ...prev,
                      [task.id]: { ...prev[task.id], drop: !prev[task.id]?.drop },
                    }))
                  }
                  className="shrink-0 text-xs text-zinc-500 hover:text-red-400"
                >
                  {planDrafts[task.id]?.drop ? "keep" : "drop"}
                </button>
              </div>
              {!planDrafts[task.id]?.drop && (
                <textarea
                  value={planDrafts[task.id]?.description ?? ""}
                  onChange={(e) =>
                    setPlanDrafts((prev) => ({
                      ...prev,
                      [task.id]: { ...prev[task.id], description: e.target.value },
                    }))
                  }
                  placeholder="Description (optional)"
                  rows={2}
                  className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1 text-xs text-zinc-300 outline-none focus:border-zinc-600"
                />
              )}
            </div>
          ) : (
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
          ),
        )}
      </section>

      {diff && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-zinc-300">Changes</h2>
          <pre className="overflow-x-auto rounded-md border border-zinc-800 p-4 text-xs leading-5">
            {diff.split("\n").map((line, index) => (
              <div key={index} className={diffLineClass(line)}>
                {line || " "}
              </div>
            ))}
          </pre>
        </section>
      )}

      {files && files.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-zinc-300">
            Files{" "}
            <span className="font-normal text-zinc-500">— the run&apos;s workspace</span>
          </h2>
          <div className="grid gap-3 md:grid-cols-3">
            <ul className="max-h-96 space-y-0.5 overflow-auto rounded-md border border-zinc-800 p-2 text-xs md:col-span-1">
              {files.map((file) => (
                <li key={file.path}>
                  <button
                    type="button"
                    onClick={() => void openFile(file.path)}
                    className={`block w-full truncate rounded px-2 py-1 text-left ${
                      openPath === file.path
                        ? "bg-zinc-800 text-zinc-100"
                        : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
                    }`}
                    title={file.path}
                  >
                    {file.path}
                  </button>
                </li>
              ))}
              {filesTruncated && (
                <li className="px-2 py-1 text-zinc-600">… more files not shown</li>
              )}
            </ul>
            <div className="md:col-span-2">
              {!openPath && (
                <p className="rounded-md border border-zinc-800 p-4 text-xs text-zinc-500">
                  Select a file to read it.
                </p>
              )}
              {fileError && <p className="text-sm text-red-400">{fileError}</p>}
              {openPath && !fileBody && !fileError && (
                <p className="rounded-md border border-zinc-800 p-4 text-xs text-zinc-500">
                  Loading {openPath}…
                </p>
              )}
              {fileBody && (
                <div className="space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate font-mono text-xs text-zinc-500">{openPath}</p>
                    {editable && (
                      <button
                        type="button"
                        onClick={() => void saveFile()}
                        disabled={saving || draft === fileBody.content}
                        className="shrink-0 rounded-md bg-zinc-100 px-3 py-1 text-xs font-medium text-zinc-900 disabled:opacity-50"
                      >
                        {saving ? "Saving…" : "Save"}
                      </button>
                    )}
                  </div>
                  {editable ? (
                    <textarea
                      value={draft ?? ""}
                      onChange={(e) => setDraft(e.target.value)}
                      spellCheck={false}
                      className="h-96 w-full rounded-md border border-zinc-800 bg-zinc-950 p-4 font-mono text-xs leading-5 text-zinc-300 outline-none focus:border-zinc-600"
                    />
                  ) : (
                    <pre className="max-h-96 overflow-auto rounded-md border border-zinc-800 p-4 text-xs leading-5 text-zinc-300">
                      {fileBody.content || "(empty file)"}
                    </pre>
                  )}
                  {fileBody.truncated && (
                    <p className="text-xs text-zinc-600">… file truncated at the view limit</p>
                  )}
                </div>
              )}
            </div>
          </div>

          {editable && (
            <div className="space-y-2 rounded-md border border-zinc-800 p-4">
              <h3 className="text-xs font-semibold text-zinc-400">Working tree</h3>
              {gitChanges.length === 0 ? (
                <p className="text-xs text-zinc-500">No uncommitted changes.</p>
              ) : (
                <ul className="space-y-0.5 font-mono text-xs">
                  {gitChanges.map((change) => (
                    <li key={change.path} className="text-amber-300">
                      <span className="text-zinc-500">{change.code}</span> {change.path}
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex gap-2">
                <input
                  value={commitMessage}
                  onChange={(e) => setCommitMessage(e.target.value)}
                  placeholder="Commit message"
                  className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs outline-none focus:border-zinc-500"
                />
                <button
                  type="button"
                  onClick={() => void commitWorkspace()}
                  disabled={committing || !commitMessage.trim() || gitChanges.length === 0}
                  className="shrink-0 rounded-md bg-zinc-100 px-3 py-1.5 text-xs font-medium text-zinc-900 disabled:opacity-50"
                >
                  {committing ? "Committing…" : "Commit"}
                </button>
                <button
                  type="button"
                  onClick={() => void pushBranch()}
                  disabled={pushing || committing}
                  title="Push the run's branch to its host — the existing pull request updates"
                  className="shrink-0 rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-400 disabled:opacity-50"
                >
                  {pushing ? "Pushing…" : "Push branch"}
                </button>
              </div>
              {workspaceNote && <p className="text-xs text-zinc-500">{workspaceNote}</p>}
            </div>
          )}
        </section>
      )}

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
