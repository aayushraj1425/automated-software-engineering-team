// @vitest-environment node
// (jsdom's TextEncoder yields a cross-realm Uint8Array that jose rejects)
//
// The service JWT carries the active organization (or nothing) — verified
// against the decoded token itself, not the implementation.

import { jwtVerify } from "jose";
import { describe, expect, it } from "vitest";

import { env } from "@/lib/env";
import { signServiceToken } from "@/lib/service-token";

const secret = new TextEncoder().encode(env.ENGINE_SERVICE_SECRET);

describe("signServiceToken", () => {
  it("asserts the user and the active organization", async () => {
    const token = await signServiceToken({
      user: { id: "user_1" },
      session: { activeOrganizationId: "org_42" },
    });
    const { payload } = await jwtVerify(token, secret);
    expect(payload.sub).toBe("user_1");
    expect(payload.org).toBe("org_42");
    expect(payload.exp).toBeDefined();
  });

  it("omits the org claim without an active organization", async () => {
    const token = await signServiceToken({
      user: { id: "user_1" },
      session: { activeOrganizationId: null },
    });
    const { payload } = await jwtVerify(token, secret);
    expect(payload.sub).toBe("user_1");
    expect(payload.org).toBeUndefined();
  });
});
