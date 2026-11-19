import type { CatalogModel, TeamSeat } from "./types";

/** Display names for the seat levels the engine uses. */
const LEVEL_NAMES: Record<string, string> = {
  principal: "Principal",
  senior: "Senior",
  engineer: "Engineer",
  support: "Support",
};

export function levelName(level: string): string {
  return LEVEL_NAMES[level] ?? level.charAt(0).toUpperCase() + level.slice(1);
}

/** "backend:engineer" → "Backend (Engineer)". Falls back to the raw key. */
export function seatLabel(key: string): string {
  const [role, level] = key.split(":");
  if (!role) return key;
  const name = role
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
  return level ? `${name} (${levelName(level)})` : name;
}

/** The model id without its provider prefix, e.g. "anthropic/claude-opus-5-5" →
 * "claude-opus-5-5". */
export function shortModel(model: string | null | undefined): string {
  if (!model) return "auto";
  const slash = model.indexOf("/");
  return slash >= 0 ? model.slice(slash + 1) : model;
}

export type ModelOption = {
  /** The full catalog id sent to the engine. */
  id: string;
  /** What the select shows. */
  label: string;
};

function priceText(model: CatalogModel): string {
  return `$${model.input_cost_per_million}/$${model.output_cost_per_million} per 1M tokens`;
}

function optionLabel(model: CatalogModel): string {
  const notes = [`strength ${model.strength}`, priceText(model)];
  if (model.open_source && !model.evaluated) notes.push("not evaluated");
  return `${shortModel(model.id)} (${notes.join(", ")})`;
}

/** The models a seat's select may offer: only catalog models that support tool
 * calls (every seat uses tools), strongest first and then cheapest, so the
 * ordering is stable and the trade-off reads top to bottom. The seat's current
 * model is always kept, even when the catalog no longer lists it, so a select
 * never silently displays a different model than the one stored. */
export function modelOptions(catalog: CatalogModel[], current?: string | null): ModelOption[] {
  const usable = catalog
    .filter((model) => model.supports_tools)
    .sort(
      (a, b) =>
        b.strength - a.strength ||
        a.input_cost_per_million +
          a.output_cost_per_million -
          (b.input_cost_per_million + b.output_cost_per_million) ||
        a.id.localeCompare(b.id),
    );
  const options = usable.map((model) => ({ id: model.id, label: optionLabel(model) }));
  if (current && !options.some((option) => option.id === current)) {
    options.unshift({ id: current, label: `${shortModel(current)} (not in the catalog)` });
  }
  return options;
}

/** The override map after the person picks `modelId` for one seat. An empty
 * choice means Auto, which removes the seat from the map; the engine then picks
 * for it. Returns a new object. */
export function withOverride(
  overrides: Record<string, string>,
  seatKey: string,
  modelId: string,
): Record<string, string> {
  const next = { ...overrides };
  if (modelId) next[seatKey] = modelId;
  else delete next[seatKey];
  return next;
}

/** Is this seat's model pinned by hand rather than chosen by the engine? */
export function isPinned(seat: TeamSeat, overrides: Record<string, string>): boolean {
  return seat.key in overrides;
}
