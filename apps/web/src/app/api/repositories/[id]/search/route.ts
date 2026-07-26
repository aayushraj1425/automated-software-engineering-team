import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  const q = new URL(req.url).searchParams.get("q") ?? "";
  return proxyToEngine(
    req,
    `/v1/repositories/${encodeURIComponent(id)}/search?q=${encodeURIComponent(q)}`,
  );
}
