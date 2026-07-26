import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  const after = new URL(req.url).searchParams.get("after") ?? "0";
  return proxyToEngine(
    req,
    `/v1/runs/${encodeURIComponent(id)}/events?after=${encodeURIComponent(after)}`,
  );
}
