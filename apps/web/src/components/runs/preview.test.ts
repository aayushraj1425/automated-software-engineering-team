import { describe, expect, it } from "vitest";

import { deploymentStatusLabel, parsePreview } from "./preview";

const base = {
  run_id: "r1",
  namespace: "asep-preview-abcd",
  expires_at: "2026-11-18T12:00:00Z",
  source_sha: "0123456789abcdef0123",
};

describe("parsePreview", () => {
  it("returns null when there is no deployment to show", () => {
    expect(parsePreview(null)).toBeNull();
    expect(parsePreview(undefined)).toBeNull();
    expect(parsePreview({})).toBeNull();
  });

  it("links the URL only for a live deployment", () => {
    const live = parsePreview({
      ...base,
      status: "deployed",
      url: "https://preview.example.com",
      smoke: { passed: true, checks: [{ path: "/healthz", ok: true, status_code: 200 }] },
    });
    expect(live?.live).toBe(true);
    expect(live?.href).toBe("https://preview.example.com");
    expect(live?.smoke?.passed).toBe(true);
    expect(live?.smoke?.checks[0]).toEqual({ path: "/healthz", ok: true, detail: "HTTP 200" });
  });

  it("never makes a simulated deployment look live or clickable", () => {
    const simulated = parsePreview({
      ...base,
      status: "simulated",
      url: "https://simulated.invalid",
      smoke: { passed: true, checks: [] },
    });
    expect(simulated?.status).toBe("simulated");
    expect(simulated?.live).toBe(false);
    expect(simulated?.href).toBeNull();
    expect(simulated?.url).toBe("https://simulated.invalid");
  });

  it("refuses to link a non-http URL even on a live deployment", () => {
    const info = parsePreview({ ...base, status: "deployed", url: "javascript:alert(1)" });
    expect(info?.href).toBeNull();
    const file = parsePreview({ ...base, status: "deployed", url: "file:///etc/passwd" });
    expect(file?.href).toBeNull();
  });

  it("treats an unknown status as unknown and not live", () => {
    const info = parsePreview({ ...base, status: "weird", url: "https://x.example.com" });
    expect(info?.status).toBe("unknown");
    expect(info?.href).toBeNull();
  });

  it("bounds text and checks, and ignores unknown fields", () => {
    const checks = Array.from({ length: 50 }, (_, i) => ({ path: `/p${i}`, ok: true }));
    const info = parsePreview({
      ...base,
      status: "failed",
      error: "x".repeat(1000),
      kubeconfig: "SECRET",
      smoke: { passed: false, checks },
    });
    expect(info?.error?.length).toBeLessThanOrEqual(301);
    expect(info?.smoke?.checks).toHaveLength(20);
    expect(JSON.stringify(info)).not.toContain("SECRET");
  });

  it("survives malformed smoke checks", () => {
    const info = parsePreview({
      ...base,
      status: "deployed",
      smoke: { passed: false, checks: [null, "oops", { path: "/ok", ok: false, error: "500" }] },
    });
    expect(info?.smoke?.checks.map((c) => c.ok)).toEqual([null, null, false]);
    expect(info?.smoke?.checks[2].detail).toBe("500");
  });
});

describe("deploymentStatusLabel", () => {
  it("reads the engine's status in plain words", () => {
    expect(deploymentStatusLabel("not_requested")).toBe("Not requested");
    expect(deploymentStatusLabel(undefined)).toBe("Not requested");
    expect(deploymentStatusLabel("approved")).toBe("Approved");
    expect(deploymentStatusLabel("awaiting_approval")).toBe("Awaiting approval");
  });
});
