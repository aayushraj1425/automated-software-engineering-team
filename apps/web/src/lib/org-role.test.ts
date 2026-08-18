// activeOrgRole gates the destructive org routes, so its two null paths matter:
// no active member, and a thrown lookup (no active organization) must both read
// as "no role", never a stray role that would over-authorize.

import { beforeEach, describe, expect, it, vi } from "vitest";

const getActiveMember = vi.fn();
vi.mock("@/lib/auth", () => ({
  auth: { api: { getActiveMember: (args: { headers: Headers }) => getActiveMember(args) } },
}));

import { activeOrgRole } from "@/lib/org-role";

beforeEach(() => {
  getActiveMember.mockReset();
});

describe("activeOrgRole", () => {
  it("returns the active member's role", async () => {
    getActiveMember.mockResolvedValue({ role: "admin" });
    await expect(activeOrgRole(new Headers())).resolves.toBe("admin");
  });

  it("returns null when there is no active member", async () => {
    getActiveMember.mockResolvedValue(null);
    await expect(activeOrgRole(new Headers())).resolves.toBeNull();
  });

  it("returns null when the lookup throws (no active organization)", async () => {
    getActiveMember.mockRejectedValue(new Error("no active organization"));
    await expect(activeOrgRole(new Headers())).resolves.toBeNull();
  });
});
