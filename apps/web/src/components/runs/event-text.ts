import type { RunEvent } from "./types";

/** Nice display name for an agent role, e.g. "product_manager" → "Product Manager". */
export function agentName(role: string | null): string {
  if (!role) return "System";
  return role
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** The distinct agents that appear in a run's events, in first-appearance
 * order, each with how many lines it produced. Run-level and human actions
 * (no agent) collapse into one `null` entry — the "System" chip. Powers the
 * timeline filter. Design note: docs/architecture/TIMELINE_AGENT_FILTER.md. */
export function timelineAgents(
  events: RunEvent[],
): { agent: string | null; count: number }[] {
  const order: (string | null)[] = [];
  const counts = new Map<string | null, number>();
  for (const event of events) {
    if (!counts.has(event.agent)) order.push(event.agent);
    counts.set(event.agent, (counts.get(event.agent) ?? 0) + 1);
  }
  return order.map((agent) => ({ agent, count: counts.get(agent) ?? 0 }));
}

/** The full reasoning text an agent volunteered, for an `agent.reasoning`
 * event; `null` for any other event. The timeline shows a preview and expands
 * to this on demand, so following an agent's thinking isn't cut off at 140
 * characters. Design note: docs/architecture/AGENT_REASONING_TIMELINE.md. */
export function reasoningOf(event: RunEvent): string | null {
  if (event.type !== "agent.reasoning") return null;
  const text = String(event.payload.text ?? "").trim();
  return text.length > 0 ? text : null;
}

/** One plain-English line per timeline event. */
export function describeEvent(event: RunEvent): string {
  const p = event.payload;
  switch (event.type) {
    case "run.started":
      return `Run started: "${String(p.request ?? "")}"`;
    case "run.status_changed":
      return `Run is now ${String(p.to ?? "?").replace("_", " ")}`;
    case "plan.created":
      return `${agentName(event.agent)} wrote the plan (${
        Array.isArray(p.tasks) ? p.tasks.length : 0
      } tasks)`;
    case "task.created":
      return `${agentName(event.agent)} added a task: "${String(p.title ?? "")}"`;
    case "task.status_changed": {
      const to = String(p.to ?? "");
      const title = p.title ? ` "${String(p.title)}"` : "";
      if (to === "in_progress") return `${agentName(event.agent)} started${title}`;
      if (to === "done") return `${agentName(event.agent)} finished: ${String(p.result ?? "task done")}`;
      if (to === "failed") return `${agentName(event.agent)} failed the task`;
      if (to === "skipped")
        return p.reason
          ? `Task${title} skipped: ${String(p.reason)}`
          : `Task skipped (the run stopped first)`;
      return `Task is now ${to.replace("_", " ")}`;
    }
    case "task.attempt_failed":
      return `${agentName(event.agent)} hit an error and will retry: ${String(p.error ?? "")}`;
    case "tool.called": {
      const args = (p.args ?? {}) as Record<string, unknown>;
      const target = args.path ?? args.message ?? args.text ?? "";
      const suffix = target ? `: ${String(target)}` : "";
      const failed = p.ok === false ? " (failed)" : "";
      return `${agentName(event.agent)} used ${String(p.tool)}${suffix}${failed}`;
    }
    case "agent.reasoning": {
      const text = String(p.text ?? "").trim();
      const shown = text.length > 140 ? `${text.slice(0, 140)}…` : text;
      return `${agentName(event.agent)} is thinking: ${shown}`;
    }
    case "review.verdict":
      return p.verdict === "approve"
        ? "Reviewer approved the changes"
        : `Reviewer requested changes (${Array.isArray(p.findings) ? p.findings.length : 0} findings)`;
    case "review.revision":
      return `${agentName(event.agent)} addressed the review findings`;
    case "branch.published":
      return p.pr_url
        ? "Branch pushed and pull request opened"
        : `Branch ${String(p.branch ?? "")} pushed`;
    case "branch.pushed":
      return `Branch ${String(p.branch ?? "")} pushed by hand`;
    case "plan.edited": {
      const edited = Number(p.edited ?? 0);
      const dropped = Number(p.dropped ?? 0);
      const parts = [
        edited > 0 ? `${edited} task(s) edited` : "",
        dropped > 0 ? `${dropped} task(s) dropped` : "",
      ].filter(Boolean);
      return `You changed the plan: ${parts.join(", ") || "no changes"}`;
    }
    case "plan.approved":
      return "You approved the plan — work begins";
    case "plan.rejected":
      return "You rejected the plan — run cancelled";
    case "run.finished":
      return p.error
        ? `Run failed: ${String(p.error)}`
        : `Run finished: ${String(p.status ?? "done")}`;
    default:
      return event.type;
  }
}
