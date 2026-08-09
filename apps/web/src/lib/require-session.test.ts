// The shared auth guard behind every signed-in page: it must hand back the
// session when there is one, and redirect to /sign-in when there isn't.

import { beforeEach, describe, expect, it, vi } from "vitest";

const getSession = vi.fn();
// Real next/navigation redirect() throws internally to halt rendering; the mock
// throws so the tests can assert the guard stops there and never returns null.
// (vi.fn records the url passed by the wrapper below regardless of the body.)
const redirect = vi.fn(() => {
  throw new Error("NEXT_REDIRECT");
});

vi.mock("next/headers", () => ({ headers: vi.fn(async () => new Headers()) }));
vi.mock("next/navigation", () => ({ redirect: (url: string) => redirect(url) }));
vi.mock("@/lib/auth", () => ({ auth: { api: { getSession: () => getSession() } } }));

import { requireSession } from "@/lib/require-session";

describe("requireSession", () => {
  beforeEach(() => {
    getSession.mockReset();
    redirect.mockClear();
  });

  it("returns the session when signed in", async () => {
    const session = { user: { id: "user_1" } };
    getSession.mockResolvedValue(session);
    await expect(requireSession()).resolves.toBe(session);
    expect(redirect).not.toHaveBeenCalled();
  });

  it("redirects to /sign-in when there is no session", async () => {
    getSession.mockResolvedValue(null);
    await expect(requireSession()).rejects.toThrow("NEXT_REDIRECT");
    expect(redirect).toHaveBeenCalledWith("/sign-in");
  });
});
