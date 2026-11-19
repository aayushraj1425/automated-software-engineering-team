/** The seat levels an organization can pin a model for, strongest first. */
export const POLICY_LEVELS = [
  { id: "principal", label: "Principal Engineer" },
  { id: "senior", label: "Senior Engineer" },
  { id: "engineer", label: "Engineer" },
  { id: "support", label: "Support" },
] as const;

export type ModelPolicy = {
  level_pins: Record<string, string>;
  allow_open_source_auto: boolean;
};

/** Read the engine's policy response defensively: unknown levels and non-string
 * pins are dropped so a malformed reply can't put junk into the form. */
export function parsePolicy(raw: unknown): ModelPolicy {
  const body = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const known = new Set<string>(POLICY_LEVELS.map((level) => level.id));
  const pins: Record<string, string> = {};
  if (body.level_pins && typeof body.level_pins === "object") {
    for (const [level, model] of Object.entries(body.level_pins as Record<string, unknown>)) {
      if (known.has(level) && typeof model === "string" && model) pins[level] = model;
    }
  }
  return { level_pins: pins, allow_open_source_auto: body.allow_open_source_auto === true };
}

/** The PUT body: a level left on Auto is simply absent from `level_pins`. */
export function policyBody(
  pins: Record<string, string>,
  allowOpenSourceAuto: boolean,
): ModelPolicy {
  return {
    level_pins: Object.fromEntries(Object.entries(pins).filter(([, model]) => model)),
    allow_open_source_auto: allowOpenSourceAuto,
  };
}
