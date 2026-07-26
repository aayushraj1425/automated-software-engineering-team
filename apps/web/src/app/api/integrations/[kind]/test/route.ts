import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ kind: string }> },
): Promise<Response> {
  const { kind } = await params;
  return proxyToEngine(req, `/v1/integrations/${encodeURIComponent(kind)}/test`, {
    method: "POST",
  });
}
