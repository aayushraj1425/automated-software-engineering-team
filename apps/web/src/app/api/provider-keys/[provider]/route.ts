import { proxyToEngine } from "@/lib/bff";
import { activeOrgRole } from "@/lib/org-role";

export const dynamic = "force-dynamic";

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ provider: string }> },
): Promise<Response> {
  const { provider } = await params;
  return proxyToEngine(req, `/v1/provider-keys/${encodeURIComponent(provider)}`, {
    method: "PUT",
    forwardBody: true,
  });
}

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ provider: string }> },
): Promise<Response> {
  const { provider } = await params;
  // Forward the shared flag so the org's key (not the personal one) is removed.
  const shared = new URL(req.url).searchParams.get("shared") === "true";
  // Destructive route: removing the team's key is gated on the caller's org
  // role (ORGANIZATION_ROLES.md) — only fetched when it matters.
  return proxyToEngine(
    req,
    `/v1/provider-keys/${encodeURIComponent(provider)}${shared ? "?shared=true" : ""}`,
    { method: "DELETE", orgRole: shared ? await activeOrgRole(req.headers) : null },
  );
}
