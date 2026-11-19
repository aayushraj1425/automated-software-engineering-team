"use client";

import { useCallback, useEffect, useState } from "react";

import { modelOptions } from "@/components/runs/roster";
import type { CatalogModel } from "@/components/runs/types";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/feedback";

import { parsePolicy, policyBody, POLICY_LEVELS } from "./model-policy";

async function errorFrom(res: Response, fallback: string): Promise<Error> {
  const body = await res.json().catch(() => null);
  return new Error(body?.detail ?? body?.error ?? `${fallback} (${res.status})`);
}

/** The organization's model policy: pin a model per seat level and choose whether
 * open source models may be picked automatically. A pin outranks auto selection
 * but not a model pinned on a single run. Saving is admin only; the engine's
 * refusal is shown as-is. */
export function ModelPolicyPanel() {
  const [pins, setPins] = useState<Record<string, string>>({});
  const [allowOpenSource, setAllowOpenSource] = useState(false);
  const [catalog, setCatalog] = useState<CatalogModel[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [policyRes, catalogRes] = await Promise.all([
        fetch("/api/model-policy"),
        fetch("/api/models"),
      ]);
      if (!policyRes.ok) throw await errorFrom(policyRes, "Could not load the model policy");
      if (!catalogRes.ok) throw await errorFrom(catalogRes, "Could not load the model catalog");
      const policy = parsePolicy(await policyRes.json());
      setPins(policy.level_pins);
      setAllowOpenSource(policy.allow_open_source_auto);
      setCatalog((await catalogRes.json()) as CatalogModel[]);
      setLoaded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the model policy");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const res = await fetch("/api/model-policy", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(policyBody(pins, allowOpenSource)),
      });
      if (!res.ok) throw await errorFrom(res, "Could not save the model policy");
      const saved = parsePolicy(await res.json().catch(() => null));
      setPins(saved.level_pins);
      setAllowOpenSource(saved.allow_open_source_auto);
      setNote("Saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the model policy");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Model policy</h2>
        <p className="text-xs text-zinc-500">
          Pin a model for a seat level across your active organization. A model pinned on a single
          run still wins; everything left on Auto is chosen by strength and price. Only organization
          admins can save.
        </p>
      </section>

      <section className="space-y-3 rounded-md border border-zinc-800 p-4">
        {POLICY_LEVELS.map(({ id, label }) => (
          <label key={id} className="flex items-center justify-between gap-3 text-sm">
            <span className="text-zinc-200">{label}</span>
            <select
              aria-label={`${label} model`}
              value={pins[id] ?? ""}
              disabled={!loaded || busy}
              onChange={(event) => {
                const model = event.target.value;
                setPins((prev) => {
                  const next = { ...prev };
                  if (model) next[id] = model;
                  else delete next[id];
                  return next;
                });
              }}
              className="max-w-xs rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs"
            >
              <option value="">Auto</option>
              {modelOptions(catalog, pins[id]).map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ))}
        <label className="flex items-center gap-2 text-xs text-zinc-500">
          <input
            type="checkbox"
            checked={allowOpenSource}
            disabled={!loaded || busy}
            onChange={(event) => setAllowOpenSource(event.target.checked)}
          />
          Allow open source models in auto selection (only ones with passing evaluation results)
        </label>
        <div className="flex items-center gap-3">
          <Button type="button" onClick={() => void save()} disabled={!loaded || busy}>
            {busy ? "Saving…" : "Save policy"}
          </Button>
          {note && <span className="text-xs text-emerald-400">{note}</span>}
        </div>
        <FormError message={error} />
      </section>
    </div>
  );
}
