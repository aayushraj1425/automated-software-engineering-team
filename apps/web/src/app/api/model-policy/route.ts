import { proxyToEngine } from "@/lib/bff";
import { activeOrgRole } from "@/lib/org-role";

export const dynamic = "force-dynamic";

/** The active organization's model policy (level pins, open source in auto). */
export async function GET(req: Request): Promise<Response> {
  return proxyToEngine(req, "/v1/model-policy");
}

/** Writes are admin only, so the caller's organization role is signed into the
 * service token (docs/architecture/identity-integrations/ORGANIZATION_ROLES.md). */
export async function PUT(req: Request): Promise<Response> {
  return proxyToEngine(req, "/v1/model-policy", {
    method: "PUT",
    forwardBody: true,
    orgRole: await activeOrgRole(req.headers),
  });
}
