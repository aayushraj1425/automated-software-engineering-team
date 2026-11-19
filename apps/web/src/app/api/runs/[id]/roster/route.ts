import { proxyToEngine } from "@/lib/bff";

export const dynamic = "force-dynamic";

/** Change per-seat model overrides before plan approval; the engine answers with
 * the full run detail. An empty `model_overrides` map restores auto selection. */
export async function PATCH(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return proxyToEngine(req, `/v1/runs/${encodeURIComponent(id)}/roster`, {
    method: "PATCH",
    forwardBody: true,
  });
}
