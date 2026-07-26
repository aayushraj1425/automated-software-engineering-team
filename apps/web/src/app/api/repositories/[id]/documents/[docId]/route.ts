import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string; docId: string }> },
): Promise<Response> {
  const { id, docId } = await params;
  return proxyToEngine(
    req,
    `/v1/repositories/${encodeURIComponent(id)}/documents/${encodeURIComponent(docId)}`,
    { method: "PUT", forwardBody: true },
  );
}

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ id: string; docId: string }> },
): Promise<Response> {
  const { id, docId } = await params;
  return proxyToEngine(
    req,
    `/v1/repositories/${encodeURIComponent(id)}/documents/${encodeURIComponent(docId)}`,
    { method: "DELETE" },
  );
}
