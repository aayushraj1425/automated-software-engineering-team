import { describe, expect, it } from "vitest";

import { agentName, describeEvent, reasoningOf, timelineAgents } from "./event-text";
import type { RunEvent } from "./types";

function event(
  type: string,
  payload: Record<string, unknown>,
  agent: string | null = null,
): RunEvent {
  return { id: 1, type, agent, task_id: null, payload, created_at: "2026-07-04T12:00:00Z" };
}

describe("agentName", () => {
  it("turns role ids into display names", () => {
    expect(agentName("product_manager")).toBe("Product Manager");
    expect(agentName("backend")).toBe("Backend");
    expect(agentName(null)).toBe("System");
  });
});

describe("reasoningOf", () => {
  it("returns the full trace for a reasoning event, untruncated", () => {
    const long = "x".repeat(500);
    expect(reasoningOf(event("agent.reasoning", { text: long }, "backend"))).toBe(long);
    expect(reasoningOf(event("agent.reasoning", { text: "  trimmed  " }, "qa"))).toBe("trimmed");
  });

  it("is null for non-reasoning or empty events", () => {
    expect(reasoningOf(event("tool.called", { tool: "write_file" }, "backend"))).toBeNull();
    expect(reasoningOf(event("agent.reasoning", { text: "   " }, "backend"))).toBeNull();
  });
});

describe("timelineAgents", () => {
  it("lists distinct agents in first-appearance order with counts", () => {
    const events = [
      event("run.started", {}), // System (null)
      event("plan.created", { tasks: [] }, "product_manager"),
      event("task.status_changed", { to: "in_progress" }, "backend"),
      event("tool.called", { tool: "write_file" }, "backend"),
      event("plan.approved", {}), // System again
    ];
    expect(timelineAgents(events)).toEqual([
      { agent: null, count: 2 },
      { agent: "product_manager", count: 1 },
      { agent: "backend", count: 2 },
    ]);
  });

  it("is empty when there are no events", () => {
    expect(timelineAgents([])).toEqual([]);
  });
});

describe("describeEvent", () => {
  it("describes the run lifecycle in plain English", () => {
    expect(describeEvent(event("run.started", { request: "Add login" }))).toBe(
      'Run started: "Add login"',
    );
    expect(describeEvent(event("run.status_changed", { from: "queued", to: "planning" }))).toBe(
      "Run is now planning",
    );
    expect(describeEvent(event("plan.created", { tasks: ["a", "b"] }, "product_manager"))).toBe(
      "Product Manager wrote the plan (2 tasks)",
    );
    expect(describeEvent(event("run.finished", { status: "completed", error: null }))).toBe(
      "Run finished: completed",
    );
    expect(describeEvent(event("run.finished", { status: "failed", error: "boom" }))).toBe(
      "Run failed: boom",
    );
  });

  it("describes task transitions with the agent's name", () => {
    expect(
      describeEvent(
        event("task.status_changed", { to: "in_progress", title: "Build it" }, "backend"),
      ),
    ).toBe('Backend started "Build it"');
    expect(
      describeEvent(event("task.status_changed", { to: "done", result: "did it" }, "backend")),
    ).toBe("Backend finished: did it");
    expect(describeEvent(event("task.status_changed", { to: "skipped" }))).toBe(
      "Task skipped (the run stopped first)",
    );
  });

  it("describes the human's plan edits", () => {
    expect(describeEvent(event("plan.edited", { edited: 2, dropped: 1 }))).toBe(
      "You changed the plan: 2 task(s) edited, 1 task(s) dropped",
    );
    expect(describeEvent(event("plan.edited", { edited: 1, dropped: 0 }))).toBe(
      "You changed the plan: 1 task(s) edited",
    );
  });

  it("distinguishes a manual push from the pipeline's publish", () => {
    expect(describeEvent(event("branch.pushed", { branch: "asep/run-1" }))).toBe(
      "Branch asep/run-1 pushed by hand",
    );
    expect(
      describeEvent(event("branch.published", { branch: "asep/run-1", pr_url: "https://x" })),
    ).toBe("Branch pushed and pull request opened");
  });

  it("describes the agents' own board changes", () => {
    expect(describeEvent(event("task.created", { title: "Add tests" }, "backend"))).toBe(
      'Backend added a task: "Add tests"',
    );
    expect(
      describeEvent(
        event("task.status_changed", { to: "skipped", title: "Old task", reason: "not needed" }),
      ),
    ).toBe('Task "Old task" skipped: not needed');
  });

  it("surfaces an agent's reasoning, truncating a long trace", () => {
    expect(
      describeEvent(event("agent.reasoning", { text: "I'll read the file first." }, "backend")),
    ).toBe("Backend is thinking: I'll read the file first.");

    const long = "x".repeat(200);
    const line = describeEvent(event("agent.reasoning", { text: long }, "reviewer"));
    expect(line.startsWith("Reviewer is thinking: ")).toBe(true);
    expect(line.endsWith("…")).toBe(true);
    expect(line.length).toBeLessThan(180);
  });

  it("humanizes every underscore in a status, not just the first", () => {
    // Statuses are documented to grow without a migration (db/enums.py), so a
    // future multi-word status must still read cleanly, not keep a stray "_".
    expect(describeEvent(event("run.status_changed", { to: "awaiting_plan_approval" }))).toBe(
      "Run is now awaiting plan approval",
    );
    expect(describeEvent(event("task.status_changed", { to: "waiting_on_review" }))).toBe(
      "Task is now waiting on review",
    );
  });

  it("describes model picks and team assembly", () => {
    expect(
      describeEvent(
        event(
          "model.selected",
          { model: "anthropic/claude-opus-5-5", reason: "auto: cheapest at strength 4" },
          "backend",
        ),
      ),
    ).toBe("Backend uses claude-opus-5-5 (auto: cheapest at strength 4)");
    expect(
      describeEvent(event("team.assembled", { template: "complex", roles: ["backend"] })),
    ).toBe("complex team: Backend");
    expect(
      describeEvent(
        event("team.assembled", {
          template: "complex",
          seats: [{ key: "principal_engineer:principal" }, "backend:senior"],
        }),
      ),
    ).toBe("complex team: Principal Engineer (Principal), Backend (Senior)");
    expect(describeEvent(event("team.updated", { by: "u1" }))).toBe(
      "You changed the team's models",
    );
  });

  it("describes the preview deploy and keeps simulated runs distinct", () => {
    expect(describeEvent(event("deploy.started", { namespace: "asep-preview-1" }))).toBe(
      "Preview deploy started in asep-preview-1",
    );
    expect(describeEvent(event("deploy.started", { simulated: true }))).toBe(
      "Simulated preview deploy started (no real cloud)",
    );
    expect(
      describeEvent(event("deploy.finished", { status: "deployed", url: "https://p.example.com" })),
    ).toBe("Preview deploy finished: https://p.example.com");
    expect(describeEvent(event("deploy.finished", { status: "simulated" }))).toBe(
      "Simulated preview deploy finished (no real cloud)",
    );
    expect(
      describeEvent(event("deploy.finished", { status: "failed", error: "helm failed" })),
    ).toBe("Preview deploy failed: helm failed");
    expect(describeEvent(event("deploy.approved", { by: "u1" }))).toBe(
      "You approved the preview deploy",
    );
    expect(describeEvent(event("deploy.rejected", { by: "u1" }))).toBe(
      "You rejected the preview deploy, run cancelled",
    );
  });

  it("falls back to the raw type for unknown events", () => {
    expect(describeEvent(event("something.new", {}))).toBe("something.new");
  });
});
