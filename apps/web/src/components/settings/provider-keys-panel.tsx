"use client";

import { useCallback, useEffect, useState } from "react";

const PROVIDERS = [
  { id: "anthropic", label: "Anthropic", hint: "sk-ant-…" },
  { id: "openai", label: "OpenAI", hint: "sk-proj-…" },
  { id: "gemini", label: "Google Gemini", hint: "AIza…" },
] as const;

type StoredKey = {
  provider: string;
  last4: string;
  updated_at: string;
};

/** Bring-your-own provider keys: set, replace, or remove — the key itself
 * never comes back from the server, only which providers are configured. */
export function ProviderKeysPanel() {
  const [stored, setStored] = useState<StoredKey[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const res = await fetch("/api/provider-keys");
    if (res.ok) setStored(await res.json());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function save(provider: string) {
    const key = (drafts[provider] ?? "").trim();
    if (!key) return;
    setBusy(provider);
    setError(null);
    try {
      const res = await fetch(`/api/provider-keys/${provider}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ key }),
      });
      if (!res.ok) throw new Error(`Could not save the key (${res.status})`);
      setDrafts((prev) => ({ ...prev, [provider]: "" }));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  async function remove(provider: string) {
    setBusy(provider);
    setError(null);
    try {
      const res = await fetch(`/api/provider-keys/${provider}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) {
        throw new Error(`Could not remove the key (${res.status})`);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  const byProvider = new Map(stored.map((k) => [k.provider, k]));

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Model provider keys</h2>
        <p className="text-xs text-zinc-500">
          Bring your own key and your chats and agent runs spend your quota instead of the
          server&apos;s. Keys are encrypted at rest and never shown again — only the last four
          characters. Providers without a key fall back to the server&apos;s configuration.
        </p>
      </section>

      {PROVIDERS.map(({ id, label, hint }) => {
        const existing = byProvider.get(id);
        return (
          <section key={id} className="space-y-2 rounded-md border border-zinc-800 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-zinc-200">{label}</p>
              {existing ? (
                <span className="text-xs text-emerald-400">
                  key ending in {existing.last4} ·{" "}
                  {new Date(existing.updated_at).toLocaleDateString()}
                </span>
              ) : (
                <span className="text-xs text-zinc-600">no key — server default</span>
              )}
            </div>
            <div className="flex gap-3">
              <input
                type="password"
                value={drafts[id] ?? ""}
                onChange={(e) => setDrafts((prev) => ({ ...prev, [id]: e.target.value }))}
                placeholder={existing ? `Replace the key (${hint})` : `Paste a key (${hint})`}
                autoComplete="off"
                className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
              />
              <button
                type="button"
                onClick={() => void save(id)}
                disabled={busy === id || !(drafts[id] ?? "").trim()}
                className="shrink-0 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
              >
                {busy === id ? "Saving…" : existing ? "Replace" : "Save"}
              </button>
              {existing && (
                <button
                  type="button"
                  onClick={() => void remove(id)}
                  disabled={busy === id}
                  className="shrink-0 rounded-md border border-red-800 px-4 py-2 text-sm text-red-300 disabled:opacity-50"
                >
                  Remove
                </button>
              )}
            </div>
          </section>
        );
      })}

      {error && <p className="text-sm text-red-400">{error}</p>}
    </div>
  );
}
