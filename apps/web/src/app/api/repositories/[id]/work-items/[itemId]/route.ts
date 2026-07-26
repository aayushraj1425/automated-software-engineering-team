import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function PATCH(
  req: Request,
  { params }: { params: Promise<{ id: string; itemId: string }> },
): Promise<Response> {
  const { id, itemId } = await params;
  return proxyToEngine(
    req,
    `/v1/repositories/${encodeURIComponent(id)}/work-items/${encodeURIComponent(itemId)}`,
    { method: "PATCH", forwardBody: true },
  );
}
