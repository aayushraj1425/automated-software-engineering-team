import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function PATCH(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return proxyToEngine(req, `/v1/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    forwardBody: true,
  });
}

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return proxyToEngine(req, `/v1/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}
