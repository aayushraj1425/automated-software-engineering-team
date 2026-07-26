import { proxyToEngine } from "@/lib/bff";
import { activeOrgRole } from "@/lib/org-role";

export const dynamic = "force-dynamic";

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  // Destructive route: the engine gates a shared repository's disconnect on
  // the caller's org role (ORGANIZATION_ROLES.md).
  return proxyToEngine(req, `/v1/repositories/${encodeURIComponent(id)}`, {
    method: "DELETE",
    orgRole: await activeOrgRole(req.headers),
  });
}
