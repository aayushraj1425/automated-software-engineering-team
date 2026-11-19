import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RunsPanel } from "./runs-panel";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

let creation: Record<string, unknown> | undefined;
let failure: string | undefined;

beforeEach(() => {
  creation = undefined;
  failure = undefined;
  push.mockReset();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        creation = JSON.parse(String(init.body));
        return failure
          ? Response.json({ detail: failure }, { status: 422 })
          : Response.json({ id: "new-run" });
      }
      return Response.json(url.endsWith("/stats") ? { total: 0 } : []);
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function fillRequest() {
  fireEvent.change(screen.getByLabelText("Repository URL"), {
    target: { value: "https://github.com/acme/app" },
  });
  fireEvent.change(screen.getByLabelText("What you want built"), {
    target: { value: "Add a status endpoint" },
  });
}

describe("run creation preview settings", () => {
  it("leaves inference to the engine by default and can explicitly disable deployment", async () => {
    render(<RunsPanel />);
    fillRequest();
    fireEvent.change(screen.getByLabelText("Preview deployment"), { target: { value: "off" } });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/runs/new-run"));
    expect(creation?.preview_requested).toBe(false);
    expect(creation).not.toHaveProperty("preview_options");
  });

  it("sends the configured chart, published image and smoke paths for a requested preview", async () => {
    render(<RunsPanel />);
    fillRequest();
    fireEvent.change(screen.getByLabelText("Preview deployment"), { target: { value: "request" } });
    fireEvent.change(screen.getByLabelText("Helm chart path"), { target: { value: "charts/app" } });
    fireEvent.change(screen.getByLabelText("Published image (optional)"), {
      target: { value: "registry.example/app:review" },
    });
    fireEvent.change(screen.getByLabelText("Smoke paths (comma separated)"), {
      target: { value: "/health, /ready" },
    });
    fireEvent.change(screen.getByLabelText("Lifetime in hours"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(creation?.preview_requested).toBe(true);
    expect(creation?.preview_options).toEqual({
      chart_path: "charts/app",
      values_file: null,
      image: "registry.example/app:review",
      ttl_hours: 2,
      smoke_paths: ["/health", "/ready"],
    });
  });

  it("shows a deployment configuration refusal from the engine", async () => {
    failure = "Preview deployment requires an active organization";
    render(<RunsPanel />);
    fillRequest();
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByText(failure)).toBeInTheDocument();
    expect(creation).not.toHaveProperty("preview_requested");
    expect(push).not.toHaveBeenCalled();
  });
});
