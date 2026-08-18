// Which OAuth buttons the sign-in/up pages show is decided here: a provider
// appears only when BOTH its client id and secret are configured, so a
// half-configured provider never renders a dead button.

import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockEnv } = vi.hoisted(() => ({
  mockEnv: {} as Record<string, string | undefined>,
}));
vi.mock("@/lib/env", () => ({ env: mockEnv }));

import { configuredProviders } from "@/lib/sign-in-providers";

beforeEach(() => {
  for (const key of Object.keys(mockEnv)) delete mockEnv[key];
});

describe("configuredProviders", () => {
  it("lists a provider when both its id and secret are set", () => {
    mockEnv.GITHUB_CLIENT_ID = "id";
    mockEnv.GITHUB_CLIENT_SECRET = "secret";
    expect(configuredProviders()).toEqual([{ id: "github", label: "GitHub" }]);
  });

  it("omits a provider that has an id but no secret", () => {
    mockEnv.GOOGLE_CLIENT_ID = "id"; // secret missing
    expect(configuredProviders()).toEqual([]);
  });

  it("lists all three in a stable order when fully configured", () => {
    mockEnv.GITHUB_CLIENT_ID = "a";
    mockEnv.GITHUB_CLIENT_SECRET = "b";
    mockEnv.GOOGLE_CLIENT_ID = "c";
    mockEnv.GOOGLE_CLIENT_SECRET = "d";
    mockEnv.MICROSOFT_CLIENT_ID = "e";
    mockEnv.MICROSOFT_CLIENT_SECRET = "f";
    expect(configuredProviders().map((p) => p.id)).toEqual(["github", "google", "microsoft"]);
  });

  it("returns an empty list when nothing is configured", () => {
    expect(configuredProviders()).toEqual([]);
  });
});
