import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

/** The model catalog the roster's per-seat selects are built from. */
export async function GET(req: Request): Promise<Response> {
  return proxyToEngine(req, "/v1/models");
}
