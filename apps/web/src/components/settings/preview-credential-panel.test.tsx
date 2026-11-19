import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PreviewCredentialPanel } from "./preview-credential-panel";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const SECRET = "apiVersion: v1\nclusters: [{name: prod-secret-cluster}]";

let configured: { configured: boolean; updated_at: string | null };
let putBodies: unknown[];

beforeEach(() => {
  configured = { configured: false, updated_at: null };
  putBodies = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "PUT") {
        putBodies.push(JSON.parse(String(init?.body)));
        configured = { configured: true, updated_at: "2026-11-17T10:00:00Z" };
        return json({ configured: true });
      }
      if (method === "DELETE") {
        configured = { configured: false, updated_at: null };
        return new Response(null, { status: 204 });
      }
      return json(configured);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PreviewCredentialPanel", () => {
  it("sends the kubeconfig once, clears the form, and never shows it back", async () => {
    render(<PreviewCredentialPanel />);
    expect(await screen.findByText(/not configured/)).toBeInTheDocument();

    const box = screen.getByLabelText("Kubeconfig") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: SECRET } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(putBodies).toEqual([{ kubeconfig: SECRET }]));
    await screen.findByText(/configured ·/);
    expect(box.value).toBe("");
    expect(document.body.textContent).not.toContain("prod-secret-cluster");
  });

  it("removes the credential", async () => {
    configured = { configured: true, updated_at: "2026-11-17T10:00:00Z" };
    render(<PreviewCredentialPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    expect(await screen.findByText(/not configured/)).toBeInTheDocument();
  });

  it("shows the engine's refusal when saving is not allowed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
        init?.method === "PUT"
          ? json({ detail: "Admin role required" }, 403)
          : json({ configured: false, updated_at: null }),
      ),
    );
    render(<PreviewCredentialPanel />);
    await screen.findByText(/not configured/);
    fireEvent.change(screen.getByLabelText("Kubeconfig"), { target: { value: SECRET } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Admin role required")).toBeInTheDocument();
    // A failed save keeps the draft so nothing is lost.
    expect((screen.getByLabelText("Kubeconfig") as HTMLTextAreaElement).value).toBe(SECRET);
  });

  it("explains a missing status endpoint instead of hanging on checking", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "Not Found" }, 404)),
    );
    render(<PreviewCredentialPanel />);
    expect(await screen.findByText("Not Found")).toBeInTheDocument();
  });
});
