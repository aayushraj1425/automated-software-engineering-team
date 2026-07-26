// @vitest-environment node
// (jose signs the service token here, and jsdom's TextEncoder yields a
// cross-realm Uint8Array that jose rejects — same reason as service-token.test)
//
// proxyToEngine is the one place the BFF authenticates, forwards, and relays.
// The session and the engine fetch are mocked so the test asserts the proxy's
// own behavior — the 401/400 guards, the 204 passthrough, and the status +
// body + auth-header relay — not the network.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getSession } = vi.hoisted(() => ({ getSession: vi.fn() }));
vi.mock("@/lib/auth", () => ({ auth: { api: { getSession } } }));

import { proxyToEngine } from "@/lib/bff";

const LOGGED_IN = { user: { id: "user_1" }, session: { activeOrganizationId: null } };

function jsonResponse(bodyText: string, status: number): Response {
  return new Response(bodyText, { status, headers: { "content-type": "application/json" } });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  getSession.mockReset();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("proxyToEngine", () => {
  it("returns 401 and never calls the engine without a session", async () => {
    getSession.mockResolvedValue(null);
    const res = await proxyToEngine(new Request("http://web/api/runs"), "/v1/runs");
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("relays the engine's status and JSON body", async () => {
    getSession.mockResolvedValue(LOGGED_IN);
    fetchMock.mockResolvedValue(jsonResponse(JSON.stringify([{ id: "run_1" }]), 200));

    const res = await proxyToEngine(new Request("http://web/api/runs"), "/v1/runs");

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual([{ id: "run_1" }]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/v1/runs");
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).authorization).toMatch(/^Bearer /);
  });

  it("relays a non-2xx status and survives an empty error body", async () => {
    getSession.mockResolvedValue(LOGGED_IN);
    fetchMock.mockResolvedValue(new Response("", { status: 502 }));

    const res = await proxyToEngine(new Request("http://web/api/runs"), "/v1/runs");

    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({});
  });

  it("passes a 204 straight through with no body", async () => {
    getSession.mockResolvedValue(LOGGED_IN);
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    const res = await proxyToEngine(
      new Request("http://web/api/runs/1", { method: "DELETE" }),
      "/v1/runs/1",
      {
        method: "DELETE",
      },
    );

    expect(res.status).toBe(204);
    expect(await res.text()).toBe("");
  });

  it("forwards the request body as JSON when asked", async () => {
    getSession.mockResolvedValue(LOGGED_IN);
    fetchMock.mockResolvedValue(jsonResponse(JSON.stringify({ ok: true }), 200));

    const req = new Request("http://web/api/runs/1/decision", {
      method: "POST",
      body: JSON.stringify({ decision: "approve" }),
    });
    await proxyToEngine(req, "/v1/runs/1/decision", { method: "POST", forwardBody: true });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["content-type"]).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ decision: "approve" }));
  });

  it("returns 400 on an unreadable body and never calls the engine", async () => {
    getSession.mockResolvedValue(LOGGED_IN);
    const req = new Request("http://web/api/runs/1/decision", {
      method: "POST",
      body: "not json{",
    });

    const res = await proxyToEngine(req, "/v1/runs/1/decision", {
      method: "POST",
      forwardBody: true,
    });

    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
