import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  const path = new URL(req.url).searchParams.get("path") ?? "";
  return proxyToEngine(
    req,
    `/v1/runs/${encodeURIComponent(id)}/files/content?path=${encodeURIComponent(path)}`,
  );
}

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return proxyToEngine(req, `/v1/runs/${encodeURIComponent(id)}/files/content`, {
    method: "PUT",
    forwardBody: true,
  });
}
