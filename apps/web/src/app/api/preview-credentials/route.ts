import { proxyToEngine } from "@/lib/bff";
import { activeOrgRole } from "@/lib/org-role";

export const dynamic = "force-dynamic";

/** Only whether a preview cluster credential is configured; never the secret. */
export async function GET(req: Request): Promise<Response> {
  return proxyToEngine(req, "/v1/preview-credentials");
}

export async function PUT(req: Request): Promise<Response> {
  return proxyToEngine(req, "/v1/preview-credentials", {
    method: "PUT",
    forwardBody: true,
    orgRole: await activeOrgRole(req.headers),
  });
}

export async function DELETE(req: Request): Promise<Response> {
  return proxyToEngine(req, "/v1/preview-credentials", {
    method: "DELETE",
    orgRole: await activeOrgRole(req.headers),
  });
}
