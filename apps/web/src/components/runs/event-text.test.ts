import { describe, expect, it } from "vitest";

import { agentName, describeEvent } from "./event-text";
import type { RunEvent } from "./types";

function event(type: string, payload: Record<string, unknown>, agent: string | null = null): RunEvent {
  return { id: 1, type, agent, task_id: null, payload, created_at: "2026-07-04T12:00:00Z" };
}

describe("agentName", () => {
  it("turns role ids into display names", () => {
    expect(agentName("product_manager")).toBe("Product Manager");
    expect(agentName("backend")).toBe("Backend");
    expect(agentName(null)).toBe("System");
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
    expect(
      describeEvent(event("plan.created", { tasks: ["a", "b"] }, "product_manager")),
    ).toBe("Product Manager wrote the plan (2 tasks)");
    expect(describeEvent(event("run.finished", { status: "completed", error: null }))).toBe(
      "Run finished: completed",
    );
    expect(describeEvent(event("run.finished", { status: "failed", error: "boom" }))).toBe(
      "Run failed: boom",
    );
  });

  it("describes task transitions with the agent's name", () => {
    expect(
      describeEvent(event("task.status_changed", { to: "in_progress", title: "Build it" }, "backend")),
    ).toBe('Backend started "Build it"');
    expect(
      describeEvent(event("task.status_changed", { to: "done", result: "did it" }, "backend")),
    ).toBe("Backend finished: did it");
    expect(describeEvent(event("task.status_changed", { to: "skipped" }))).toBe(
      "Task skipped (the run stopped first)",
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

  it("falls back to the raw type for unknown events", () => {
    expect(describeEvent(event("something.new", {}))).toBe("something.new");
  });
});
