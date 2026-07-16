"use client";

import { useState } from "react";

import { authClient } from "@/lib/auth-client";

/** Organizations: list them, create one, and pick the active one. The active
 * organization becomes session state, and every BFF-signed service JWT
 * carries it in its `org` claim from then on — the seam org-aware sharing
 * builds on (docs/architecture/SIGN_IN_AND_ORGANIZATIONS.md). */
export function OrganizationsPanel() {
  const { data: organizations, refetch } = authClient.useListOrganizations();
  const { data: activeOrganization } = authClient.useActiveOrganization();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    const slug = trimmed
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "");
    const { error } = await authClient.organization.create({ name: trimmed, slug });
    setBusy(false);
    if (error) {
      setError(error.message ?? "Could not create the organization");
      return;
    }
    setName("");
    void refetch();
  }

  async function setActive(organizationId: string | null) {
    setBusy(true);
    setError(null);
    const { error } = await authClient.organization.setActive({ organizationId });
    setBusy(false);
    if (error) {
      setError(error.message ?? "Could not switch organization");
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Organizations</h2>
        <p className="text-xs text-zinc-500">
          Work as yourself or inside an organization. Repositories and agent runs created
          while an organization is active are shared with its members; conversations and
          provider keys stay personal.
        </p>
      </section>

      <section className="space-y-3 rounded-md border border-zinc-800 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-200">Personal (no organization)</p>
          {activeOrganization ? (
            <button
              type="button"
              onClick={() => void setActive(null)}
              disabled={busy}
              className="shrink-0 rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-400 disabled:opacity-50"
            >
              Switch to personal
            </button>
          ) : (
            <span className="text-xs text-emerald-400">active</span>
          )}
        </div>

        {(organizations ?? []).map((org) => {
          const isActive = activeOrganization?.id === org.id;
          return (
            <div key={org.id} className="flex items-center justify-between gap-3">
              <p className="text-sm text-zinc-200">
                {org.name} <span className="text-xs text-zinc-600">({org.slug})</span>
              </p>
              {isActive ? (
                <span className="text-xs text-emerald-400">active</span>
              ) : (
                <button
                  type="button"
                  onClick={() => void setActive(org.id)}
                  disabled={busy}
                  className="shrink-0 rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-400 disabled:opacity-50"
                >
                  Make active
                </button>
              )}
            </div>
          );
        })}

        <form onSubmit={create} className="flex gap-3 border-t border-zinc-800 pt-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="New organization name"
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
          <button
            type="submit"
            disabled={busy || !name.trim()}
            className="shrink-0 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
          >
            {busy ? "Working…" : "Create"}
          </button>
        </form>

        {error && <p className="text-sm text-red-400">{error}</p>}
      </section>
    </div>
  );
}
