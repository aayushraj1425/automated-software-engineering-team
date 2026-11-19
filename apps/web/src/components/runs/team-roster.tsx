"use client";

import { FormError } from "../ui/feedback";
import { agentName } from "./event-text";
import { isPinned, levelName, modelOptions, shortModel, withOverride } from "./roster";
import type { CatalogModel, TeamSeat } from "./types";

type Props = {
  team: TeamSeat[];
  overrides: Record<string, string>;
  /** The model catalog; null while loading or when it could not be loaded. */
  catalog: CatalogModel[] | null;
  /** Why the catalog is missing, shown next to the table. */
  catalogError: string | null;
  /** Models can only change while the run awaits plan approval. */
  editable: boolean;
  busy: boolean;
  /** The engine's message when the last roster change was refused. */
  error: string | null;
  /** Send the whole override map; an empty map restores auto selection. */
  onChange: (overrides: Record<string, string>) => void;
};

/** The team a run will use: one row per seat with its level, model and the
 * reason the engine gave. Before approval each model is a select limited to the
 * catalog's tool-capable models; afterwards the table is a read-only record.
 * Design note: docs/architecture/runs-ui/APPROVAL_ROSTER_AND_DEPLOY_CONTROLS.md. */
export function TeamRoster({
  team,
  overrides,
  catalog,
  catalogError,
  editable,
  busy,
  error,
  onChange,
}: Props) {
  if (team.length === 0) return null;
  const canEdit = editable && catalog !== null;
  const pinnedCount = Object.keys(overrides).length;

  return (
    <section className="space-y-2" aria-label="Team roster">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-zinc-300">
          Team roster <span className="font-normal text-zinc-500">· {team.length} seats</span>
        </h2>
        {editable && (
          <button
            type="button"
            onClick={() => onChange({})}
            disabled={busy || pinnedCount === 0}
            className="rounded-md border border-zinc-700 px-2.5 py-1 text-xs text-zinc-300 hover:border-zinc-400 disabled:opacity-50"
          >
            Reset all to auto
          </button>
        )}
      </div>
      <ul className="space-y-2">
        {team.map((seat) => {
          const pinned = isPinned(seat, overrides);
          const options = modelOptions(catalog ?? [], seat.model);
          const selectId = `seat-model-${seat.key.replace(/[^a-z0-9]/gi, "-")}`;
          return (
            <li
              key={seat.key}
              className="space-y-1 rounded-md border border-zinc-800 px-4 py-3"
              data-seat={seat.key}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm text-zinc-200">
                    {agentName(seat.role)}{" "}
                    <span className="text-zinc-500">· {levelName(seat.level)}</span>
                  </p>
                  <p className="font-mono text-xs text-zinc-500">{seat.key}</p>
                </div>
                {canEdit ? (
                  <div className="flex items-center gap-2">
                    <label htmlFor={selectId} className="sr-only">
                      Model for {seat.key}
                    </label>
                    <select
                      id={selectId}
                      value={pinned ? overrides[seat.key] : ""}
                      disabled={busy}
                      onChange={(event) =>
                        onChange(withOverride(overrides, seat.key, event.target.value))
                      }
                      className="max-w-xs rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs"
                    >
                      <option value="">Auto ({shortModel(seat.model)})</option>
                      {options.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <p className="font-mono text-xs text-zinc-300">
                    {shortModel(seat.model)}
                    {pinned && <span className="ml-2 text-violet-300">pinned</span>}
                  </p>
                )}
              </div>
              {seat.reason && <p className="text-xs text-zinc-500">{seat.reason}</p>}
            </li>
          );
        })}
      </ul>
      {editable && catalogError && (
        <FormError message={`Model choices are unavailable: ${catalogError}`} />
      )}
      <FormError message={error} />
    </section>
  );
}
