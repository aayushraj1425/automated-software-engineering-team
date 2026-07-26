import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const q = new URL(req.url).searchParams.get("q");
  const query = q ? `?q=${encodeURIComponent(q)}` : "";
  return proxyToEngine(req, `/v1/conversations${query}`);
}
