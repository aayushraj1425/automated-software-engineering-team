import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  const q = new URL(req.url).searchParams.get("q");
  const query = q ? `?q=${encodeURIComponent(q)}` : "";
  return proxyToEngine(req, `/v1/repositories/${encodeURIComponent(id)}/knowledge${query}`);
}

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return proxyToEngine(req, `/v1/repositories/${encodeURIComponent(id)}/knowledge`, {
    method: "POST",
    forwardBody: true,
  });
}
