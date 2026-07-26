import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ kind: string }> },
): Promise<Response> {
  const { kind } = await params;
  return proxyToEngine(req, `/v1/integrations/${encodeURIComponent(kind)}`, {
    method: "PUT",
    forwardBody: true,
  });
}

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ kind: string }> },
): Promise<Response> {
  const { kind } = await params;
  return proxyToEngine(req, `/v1/integrations/${encodeURIComponent(kind)}`, {
    method: "DELETE",
  });
}
