import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  return proxyToEngine(req, "/v1/provider-keys");
}
