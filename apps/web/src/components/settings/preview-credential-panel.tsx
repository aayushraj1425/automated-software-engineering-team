"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/feedback";

type CredentialStatus = { configured: boolean; updated_at: string | null };

async function errorFrom(res: Response, fallback: string): Promise<Error> {
  const body = await res.json().catch(() => null);
  return new Error(body?.detail ?? body?.error ?? `${fallback} (${res.status})`);
}

/** The cluster credential preview deploys use. It is write only: the kubeconfig is
 * sent once, cleared from the form, and never read back. The panel only knows
 * whether one is configured and when it last changed. Only the Release Engineer's
 * deploy step ever receives it, never a model. */
export function PreviewCredentialPanel() {
  const [status, setStatus] = useState<CredentialStatus | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/preview-credentials");
      if (!res.ok) throw await errorFrom(res, "Could not load the preview credential status");
      const body = (await res.json()) as Partial<CredentialStatus>;
      setStatus({ configured: body.configured === true, updated_at: body.updated_at ?? null });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the preview credential status");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function save() {
    const kubeconfig = draft.trim();
    if (!kubeconfig) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/preview-credentials", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ kubeconfig }),
      });
      if (!res.ok) throw await errorFrom(res, "Could not save the kubeconfig");
      setDraft(""); // the secret leaves the page as soon as it is stored
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the kubeconfig");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/preview-credentials", { method: "DELETE" });
      if (!res.ok && res.status !== 204) throw await errorFrom(res, "Could not remove it");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the credential");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Preview deploy access</h2>
        <p className="text-xs text-zinc-500">
          A kubeconfig for the cluster where complex runs deploy a temporary preview, after you
          approve it. It is encrypted at rest, handed only to the deploy step, and never shown
          again. Only organization admins can change it.
        </p>
      </section>

      <section className="space-y-3 rounded-md border border-zinc-800 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-200">Kubeconfig</p>
          {status?.configured ? (
            <span className="text-xs text-emerald-400">
              configured
              {status.updated_at && <> · {new Date(status.updated_at).toLocaleDateString()}</>}
            </span>
          ) : (
            <span className="text-xs text-zinc-600">
              {status ? "not configured, previews are simulated or skipped" : "checking…"}
            </span>
          )}
        </div>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          aria-label="Kubeconfig"
          placeholder={
            status?.configured ? "Paste a kubeconfig to replace it" : "Paste a kubeconfig"
          }
          autoComplete="off"
          spellCheck={false}
          rows={4}
          className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 font-mono text-xs outline-none focus:border-zinc-500"
        />
        <div className="flex items-center gap-3">
          <Button type="button" onClick={() => void save()} disabled={busy || !draft.trim()}>
            {busy ? "Saving…" : "Save"}
          </Button>
          {status?.configured && (
            <Button type="button" variant="danger" onClick={() => void remove()} disabled={busy}>
              Remove
            </Button>
          )}
        </div>
        <FormError message={error} />
      </section>
    </div>
  );
}
