import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  // Forward the known filters through to the engine — status and text search.
  const params = new URL(req.url).searchParams;
  const forward = new URLSearchParams();
  const status = params.get("status");
  const q = params.get("q");
  if (status) forward.set("status", status);
  if (q) forward.set("q", q);
  const query = forward.toString() ? `?${forward}` : "";
  return proxyToEngine(req, `/v1/runs${query}`);
}

export async function POST(req: Request): Promise<Response> {
  return proxyToEngine(req, "/v1/runs", { method: "POST", forwardBody: true });
}
