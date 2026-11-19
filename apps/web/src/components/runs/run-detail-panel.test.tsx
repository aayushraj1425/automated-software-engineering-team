// The run screen's approval flows: per-seat model overrides before approval and
// the second approval for a preview deploy. fetch and EventSource are stubbed, so
// the test checks what the screen sends to the BFF and how it shows the answer.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { RunDetailPanel } from "./run-detail-panel";
import type { RunDetail } from "./types";

const CATALOG = [
  {
    id: "anthropic/claude-fable-5-2",
    provider: "anthropic",
    context_size: 200000,
    supports_tools: true,
    strength: 5,
    input_cost_per_million: 15,
    output_cost_per_million: 75,
    open_source: false,
    evaluated: false,
  },
  {
    id: "anthropic/claude-sonnet-5-5",
    provider: "anthropic",
    context_size: 200000,
    supports_tools: true,
    strength: 3,
    input_cost_per_million: 3,
    output_cost_per_million: 15,
    open_source: false,
    evaluated: false,
  },
];

function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "run-1",
    status: "awaiting_approval",
    request: "Add billing and deploy it",
    repository_url: "https://github.com/acme/app",
    error: null,
    pr_url: null,
    created_at: "2026-11-17T10:00:00Z",
    started_at: null,
    finished_at: null,
    complexity: "complex",
    triage_reason: "mentions deploy",
    team_template: "complex",
    plan: { summary: "Billing plan", tasks: ["Add billing"] },
    tasks: [
      {
        id: "t1",
        sequence: 1,
        role: "backend",
        title: "Add billing",
        description: null,
        status: "pending",
        depends_on: [],
        result: null,
        attempts: 0,
        level: "senior",
        model: "anthropic/claude-fable-5-2",
      },
    ],
    total_cost_usd: 0,
    total_input_tokens: 0,
    total_output_tokens: 0,
    design_note: "Use a ledger table.",
    team: [
      {
        key: "backend:senior",
        role: "backend",
        level: "senior",
        model: "anthropic/claude-fable-5-2",
        reason: "auto: strongest",
      },
    ],
    model_overrides: {},
    deployment_status: "not_requested",
    ...overrides,
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

let run: RunDetail;
let handlers: Record<string, Handler>;
let calls: { url: string; init?: RequestInit }[];

beforeEach(() => {
  calls = [];
  run = runDetail();
  handlers = {};
  class FakeEventSource {
    static CLOSED = 2;
    readyState = 1;
    onmessage = null;
    onerror = null;
    addEventListener() {}
    close() {}
  }
  vi.stubGlobal("EventSource", FakeEventSource);
  // jsdom has no layout, so the timeline's follow-the-newest scroll is a no-op here.
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      const key = `${init?.method ?? "GET"} ${url.split("?")[0]}`;
      if (handlers[key]) return handlers[key](url, init);
      if (key === "GET /api/runs/run-1") return json(run);
      if (key === "GET /api/models") return json(CATALOG);
      if (key === "GET /api/runs/run-1/files") return json({ files: [], truncated: false });
      return json({}, 404);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RunDetailPanel roster", () => {
  it("shows seats, a persisted task model and the design note", async () => {
    render(<RunDetailPanel runId="run-1" />);
    expect(await screen.findByText("backend:senior")).toBeInTheDocument();
    expect(screen.getByText("Use a ledger table.")).toBeInTheDocument();
    expect(screen.getByText(/Backend · Senior · claude-fable-5-2/)).toBeInTheDocument();
  });

  it("patches the roster and replaces the screen with the run the engine returns", async () => {
    handlers["PATCH /api/runs/run-1/roster"] = (_url, init) => {
      const sent = JSON.parse(String(init?.body));
      expect(sent).toEqual({
        model_overrides: { "backend:senior": "anthropic/claude-sonnet-5-5" },
      });
      return json(
        runDetail({
          model_overrides: sent.model_overrides,
          team: [
            {
              key: "backend:senior",
              role: "backend",
              level: "senior",
              model: "anthropic/claude-sonnet-5-5",
              reason: "pinned by you",
            },
          ],
        }),
      );
    };
    render(<RunDetailPanel runId="run-1" />);
    const select = await screen.findByLabelText("Model for backend:senior");
    // The catalog loads after the run; wait for its options to arrive.
    await waitFor(() => expect(select).toHaveProperty("options.length", 3));
    fireEvent.change(select, { target: { value: "anthropic/claude-sonnet-5-5" } });
    expect(await screen.findByText("pinned by you")).toBeInTheDocument();
    expect((screen.getByLabelText("Model for backend:senior") as HTMLSelectElement).value).toBe(
      "anthropic/claude-sonnet-5-5",
    );
  });

  it("shows the engine's reason when a roster change is refused", async () => {
    handlers["PATCH /api/runs/run-1/roster"] = () =>
      json({ detail: "Models can only change before plan approval" }, 409);
    render(<RunDetailPanel runId="run-1" />);
    const select = await screen.findByLabelText("Model for backend:senior");
    await waitFor(() => expect(select).toHaveProperty("options.length", 3));
    fireEvent.change(select, { target: { value: "anthropic/claude-sonnet-5-5" } });
    expect(
      await screen.findByText("Models can only change before plan approval"),
    ).toBeInTheDocument();
  });

  it("clears every override with an empty map", async () => {
    run = runDetail({ model_overrides: { "backend:senior": "anthropic/claude-sonnet-5-5" } });
    let sent: unknown = null;
    handlers["PATCH /api/runs/run-1/roster"] = (_url, init) => {
      sent = JSON.parse(String(init?.body));
      return json(runDetail());
    };
    render(<RunDetailPanel runId="run-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Reset all to auto" }));
    await waitFor(() => expect(sent).toEqual({ model_overrides: {} }));
  });

  it("keeps approval possible but explains it when the catalog is down", async () => {
    handlers["GET /api/models"] = () => json({ error: "Engine unavailable" }, 502);
    render(<RunDetailPanel runId="run-1" />);
    expect(
      await screen.findByText(/Model choices are unavailable: Engine unavailable/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Model for backend:senior")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve plan" })).toBeEnabled();
  });

  it("makes the roster read only once the plan is approved", async () => {
    run = runDetail({ status: "executing" });
    render(<RunDetailPanel runId="run-1" />);
    expect(await screen.findByText("backend:senior")).toBeInTheDocument();
    expect(screen.queryByLabelText("Model for backend:senior")).not.toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/models")).toBe(false);
  });

  it("shows the engine's refusal when approving the plan fails", async () => {
    handlers["POST /api/runs/run-1/decision"] = () => json({ detail: "Run is not waiting" }, 409);
    render(<RunDetailPanel runId="run-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve plan" }));
    expect(await screen.findByText("Run is not waiting")).toBeInTheDocument();
  });
});

describe("RunDetailPanel deploy approval", () => {
  beforeEach(() => {
    run = runDetail({
      status: "awaiting_deploy_approval",
      preview_requested: true,
      deployment_status: "awaiting_approval",
    });
  });

  it("posts the second approval and refetches the run", async () => {
    let body: unknown = null;
    handlers["POST /api/runs/run-1/deploy-decision"] = (_url, init) => {
      body = JSON.parse(String(init?.body));
      run = runDetail({ status: "executing", deployment_status: "approved" });
      return json({ id: "run-1", status: "executing" });
    };
    render(<RunDetailPanel runId="run-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve deploy" }));
    await waitFor(() => expect(body).toEqual({ approved: true }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Approve deploy" })).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Approved")).toBeInTheDocument();
  });

  it("posts a rejection", async () => {
    let body: unknown = null;
    handlers["POST /api/runs/run-1/deploy-decision"] = (_url, init) => {
      body = JSON.parse(String(init?.body));
      run = runDetail({ status: "cancelled", deployment_status: "rejected" });
      return json({ id: "run-1", status: "cancelled" });
    };
    render(<RunDetailPanel runId="run-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Reject deploy" }));
    await waitFor(() => expect(body).toEqual({ approved: false }));
  });

  it("shows the engine's message when the decision is refused", async () => {
    handlers["POST /api/runs/run-1/deploy-decision"] = () =>
      json({ detail: "Only the run owner or an org admin may approve deploy" }, 403);
    render(<RunDetailPanel runId="run-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve deploy" }));
    expect(
      await screen.findByText("Only the run owner or an org admin may approve deploy"),
    ).toBeInTheDocument();
    // The gate stays open so the person can try again.
    expect(screen.getByRole("button", { name: "Approve deploy" })).toBeEnabled();
  });

  it("loads the workspace files while waiting for the deploy approval", async () => {
    render(<RunDetailPanel runId="run-1" />);
    await screen.findByRole("button", { name: "Approve deploy" });
    await waitFor(() => expect(calls.some((c) => c.url === "/api/runs/run-1/files")).toBe(true));
    expect(calls.some((c) => c.url === "/api/runs/run-1/diff")).toBe(true);
  });
});
