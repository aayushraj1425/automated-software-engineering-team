// The adaptive-team BFF routes are thin proxies; what matters is that each one
// forwards to the right engine path with the right method, forwards a body only
// where one exists, and signs the org role only where the engine gates on it.

import { beforeEach, describe, expect, it, vi } from "vitest";

const { proxyToEngine, activeOrgRole } = vi.hoisted(() => ({
  proxyToEngine: vi.fn(async () => Response.json({})),
  activeOrgRole: vi.fn(async () => "admin"),
}));
vi.mock("@/lib/bff", () => ({ proxyToEngine }));
vi.mock("@/lib/org-role", () => ({ activeOrgRole }));

import * as deployDecision from "./runs/[id]/deploy-decision/route";
import * as roster from "./runs/[id]/roster/route";
import * as modelPolicy from "./model-policy/route";
import * as models from "./models/route";
import * as previewCredentials from "./preview-credentials/route";

const req = (method = "GET") => new Request("http://web/api/x", { method });
const params = (id: string) => ({ params: Promise.resolve({ id }) });

beforeEach(() => {
  proxyToEngine.mockClear();
  activeOrgRole.mockClear();
});

describe("adaptive team routes", () => {
  it("lists the model catalog", async () => {
    await models.GET(req());
    expect(proxyToEngine).toHaveBeenCalledWith(expect.any(Request), "/v1/models");
  });

  it("patches the roster with the body and an encoded run id", async () => {
    await roster.PATCH(req("PATCH"), params("a b/c"));
    expect(proxyToEngine).toHaveBeenCalledWith(expect.any(Request), "/v1/runs/a%20b%2Fc/roster", {
      method: "PATCH",
      forwardBody: true,
    });
  });

  it("posts the deploy decision with the body", async () => {
    await deployDecision.POST(req("POST"), params("run-1"));
    expect(proxyToEngine).toHaveBeenCalledWith(
      expect.any(Request),
      "/v1/runs/run-1/deploy-decision",
      { method: "POST", forwardBody: true, orgRole: "admin" },
    );
    expect(activeOrgRole).toHaveBeenCalled();
  });

  it("reads the model policy without an org role, writes it with one", async () => {
    await modelPolicy.GET(req());
    expect(proxyToEngine).toHaveBeenLastCalledWith(expect.any(Request), "/v1/model-policy");
    expect(activeOrgRole).not.toHaveBeenCalled();

    await modelPolicy.PUT(req("PUT"));
    expect(proxyToEngine).toHaveBeenLastCalledWith(expect.any(Request), "/v1/model-policy", {
      method: "PUT",
      forwardBody: true,
      orgRole: "admin",
    });
  });

  it("handles the preview credential: status, replace, remove", async () => {
    await previewCredentials.GET(req());
    expect(proxyToEngine).toHaveBeenLastCalledWith(expect.any(Request), "/v1/preview-credentials");

    await previewCredentials.PUT(req("PUT"));
    expect(proxyToEngine).toHaveBeenLastCalledWith(expect.any(Request), "/v1/preview-credentials", {
      method: "PUT",
      forwardBody: true,
      orgRole: "admin",
    });

    await previewCredentials.DELETE(req("DELETE"));
    expect(proxyToEngine).toHaveBeenLastCalledWith(expect.any(Request), "/v1/preview-credentials", {
      method: "DELETE",
      orgRole: "admin",
    });
  });
});
