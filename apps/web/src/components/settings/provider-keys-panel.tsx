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
  shared: boolean;
};

/** Bring-your-own provider keys: set, replace, or remove — the key itself
 * never comes back from the server, only which providers are configured.
 * A key can be shared with the active organization (explicitly — a secret
 * is never shared by default); your personal key outranks the team's. */
export function ProviderKeysPanel() {
  const [stored, setStored] = useState<StoredKey[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [shareDrafts, setShareDrafts] = useState<Record<string, boolean>>({});
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
        body: JSON.stringify({
          key,
          share_with_organization: shareDrafts[provider] ?? false,
        }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail ?? `Could not save the key (${res.status})`);
      }
      setDrafts((prev) => ({ ...prev, [provider]: "" }));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  async function remove(provider: string, shared: boolean) {
    setBusy(provider);
    setError(null);
    try {
      const res = await fetch(
        `/api/provider-keys/${provider}${shared ? "?shared=true" : ""}`,
        { method: "DELETE" },
      );
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

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Model provider keys</h2>
        <p className="text-xs text-zinc-500">
          Bring your own key and your chats and agent runs spend your quota instead of the
          server&apos;s. Keys are encrypted at rest and never shown again — only the last four
          characters. A key can be shared with your active organization; your personal key
          always outranks the team&apos;s, and both outrank the server default.
        </p>
      </section>

      {PROVIDERS.map(({ id, label, hint }) => {
        const entries = stored.filter((k) => k.provider === id);
        const hasAny = entries.length > 0;
        return (
          <section key={id} className="space-y-2 rounded-md border border-zinc-800 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-zinc-200">{label}</p>
              {!hasAny && <span className="text-xs text-zinc-600">no key — server default</span>}
            </div>
            {entries.map((entry) => (
              <div
                key={`${entry.provider}-${entry.shared}`}
                className="flex items-center justify-between gap-3"
              >
                <span className="text-xs text-emerald-400">
                  {entry.shared ? "team key" : "your key"} ending in {entry.last4} ·{" "}
                  {new Date(entry.updated_at).toLocaleDateString()}
                </span>
                <button
                  type="button"
                  onClick={() => void remove(id, entry.shared)}
                  disabled={busy === id}
                  className="shrink-0 text-xs text-zinc-600 hover:text-red-400 disabled:opacity-50"
                >
                  remove
                </button>
              </div>
            ))}
            <div className="flex gap-3">
              <input
                type="password"
                value={drafts[id] ?? ""}
                onChange={(e) => setDrafts((prev) => ({ ...prev, [id]: e.target.value }))}
                placeholder={hasAny ? `Replace a key (${hint})` : `Paste a key (${hint})`}
                autoComplete="off"
                className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
              />
              <button
                type="button"
                onClick={() => void save(id)}
                disabled={busy === id || !(drafts[id] ?? "").trim()}
                className="shrink-0 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
              >
                {busy === id ? "Saving…" : "Save"}
              </button>
            </div>
            <label className="flex items-center gap-2 text-xs text-zinc-500">
              <input
                type="checkbox"
                checked={shareDrafts[id] ?? false}
                onChange={(e) =>
                  setShareDrafts((prev) => ({ ...prev, [id]: e.target.checked }))
                }
              />
              Share with your active organization (any member can use and replace it)
            </label>
          </section>
        );
      })}

      {error && <p className="text-sm text-red-400">{error}</p>}
    </div>
  );
}
