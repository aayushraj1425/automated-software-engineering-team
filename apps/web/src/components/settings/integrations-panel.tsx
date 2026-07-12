"use client";

import { useCallback, useEffect, useState } from "react";

type Connection = {
  kind: string;
  label: string;
  enabled: boolean;
  updated_at: string;
};

type TestResult = { ok: boolean; dry_run: boolean; detail: string };

/** Outbound integrations. Slack is the first: save an incoming-webhook URL and
 * a run's outcome is posted there when it finishes. The webhook is encrypted at
 * rest and never returned — only a non-secret label comes back. */
export function IntegrationsPanel() {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [webhook, setWebhook] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const res = await fetch("/api/integrations");
    if (!res.ok) return;
    const rows: Connection[] = await res.json();
    setConnection(rows.find((r) => r.kind === "slack") ?? null);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function save() {
    const url = webhook.trim();
    if (!url) return;
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const res = await fetch("/api/integrations/slack", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ config: { webhook_url: url } }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail ?? `Could not save the webhook (${res.status})`);
      }
      setWebhook("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const res = await fetch("/api/integrations/slack", { method: "DELETE" });
      if (!res.ok && res.status !== 204) {
        throw new Error(`Could not disconnect (${res.status})`);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function sendTest() {
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const res = await fetch("/api/integrations/slack/test", { method: "POST" });
      const result: TestResult = await res.json();
      if (!res.ok) throw new Error(`Test failed (${res.status})`);
      setStatus(result.detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6 pt-0">
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Integrations</h2>
        <p className="text-xs text-zinc-500">
          Connect an outbound service and the platform tells it when a run finishes. Secrets
          are encrypted at rest and never shown again.
        </p>
      </section>

      <section className="space-y-2 rounded-md border border-zinc-800 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-200">Slack</p>
          {connection ? (
            <span className="text-xs text-emerald-400">
              {connection.label} · {new Date(connection.updated_at).toLocaleDateString()}
            </span>
          ) : (
            <span className="text-xs text-zinc-600">not connected</span>
          )}
        </div>
        <p className="text-xs text-zinc-500">
          Paste a Slack{" "}
          <a
            href="https://api.slack.com/messaging/webhooks"
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2 hover:text-zinc-300"
          >
            incoming-webhook URL
          </a>
          . Run outcomes are posted to that channel.
        </p>
        <div className="flex gap-3">
          <input
            type="password"
            value={webhook}
            onChange={(e) => setWebhook(e.target.value)}
            placeholder={
              connection ? "Replace the webhook (https://hooks.slack.com/…)" : "https://hooks.slack.com/…"
            }
            autoComplete="off"
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
          <button
            type="button"
            onClick={() => void save()}
            disabled={busy || !webhook.trim()}
            className="shrink-0 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
          >
            {busy ? "Saving…" : connection ? "Replace" : "Save"}
          </button>
          {connection && (
            <>
              <button
                type="button"
                onClick={() => void sendTest()}
                disabled={busy}
                className="shrink-0 rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-300 disabled:opacity-50"
              >
                Send test
              </button>
              <button
                type="button"
                onClick={() => void remove()}
                disabled={busy}
                className="shrink-0 rounded-md border border-red-800 px-4 py-2 text-sm text-red-300 disabled:opacity-50"
              >
                Remove
              </button>
            </>
          )}
        </div>
        {status && <p className="text-sm text-emerald-400">{status}</p>}
        {error && <p className="text-sm text-red-400">{error}</p>}
      </section>
    </div>
  );
}
