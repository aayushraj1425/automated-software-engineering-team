import { proxyToEngine } from "@/lib/bff";
import { activeOrgRole } from "@/lib/org-role";

export const dynamic = "force-dynamic";

/** The second human approval: `{ approved: boolean }` for the preview deploy. */
export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return proxyToEngine(req, `/v1/runs/${encodeURIComponent(id)}/deploy-decision`, {
    method: "POST",
    forwardBody: true,
    orgRole: await activeOrgRole(req.headers),
  });
}
