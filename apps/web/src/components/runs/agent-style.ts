import { agentName } from "./event-text";

/** Per-agent accent colours so each agent's thinking and actions are visually
 * distinct on the run timeline. Mirrors the status-chip colour-map pattern.
 * `role` is the engine's agent id (e.g. "product_manager"), or null for
 * run-level and human events ("System"). Design note:
 * docs/architecture/runs-ui/AGENT_TIMELINE_LEGIBILITY.md. */
export interface AgentStyle {
  /** Display name, e.g. "Product Manager". */
  label: string;
  /** Background class for the small role dot. */
  dot: string;
  /** Text class for the agent's name. */
  text: string;
  /** Left-border class for a reasoning ("thinking") card. */
  border: string;
}

const STYLES: Record<string, Omit<AgentStyle, "label">> = {
  product_manager: {
    dot: "bg-violet-400",
    text: "text-violet-300",
    border: "border-violet-500/60",
  },
  backend: { dot: "bg-sky-400", text: "text-sky-300", border: "border-sky-500/60" },
  frontend: { dot: "bg-fuchsia-400", text: "text-fuchsia-300", border: "border-fuchsia-500/60" },
  devops: { dot: "bg-orange-400", text: "text-orange-300", border: "border-orange-500/60" },
  reviewer: { dot: "bg-amber-400", text: "text-amber-300", border: "border-amber-500/60" },
  qa: { dot: "bg-emerald-400", text: "text-emerald-300", border: "border-emerald-500/60" },
  scrum_master: { dot: "bg-teal-400", text: "text-teal-300", border: "border-teal-500/60" },
  technical_writer: {
    dot: "bg-indigo-400",
    text: "text-indigo-300",
    border: "border-indigo-500/60",
  },
  supervisor: { dot: "bg-rose-400", text: "text-rose-300", border: "border-rose-500/60" },
};

const SYSTEM: Omit<AgentStyle, "label"> = {
  dot: "bg-zinc-500",
  text: "text-zinc-300",
  border: "border-zinc-600",
};

export function agentStyle(role: string | null): AgentStyle {
  const base = (role && STYLES[role]) || SYSTEM;
  return { label: agentName(role), ...base };
}
