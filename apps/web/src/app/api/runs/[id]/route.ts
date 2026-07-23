import { auth } from "@/lib/auth";
import { env } from "@/lib/env";
import { signServiceToken } from "@/lib/service-token";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const session = await auth.api.getSession({ headers: req.headers });
  if (!session) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const token = await signServiceToken(session);
  const upstream = await fetch(`${env.ENGINE_URL}/v1/runs/${encodeURIComponent(id)}`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return Response.json(await upstream.json(), { status: upstream.status });
}

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const session = await auth.api.getSession({ headers: req.headers });
  if (!session) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const token = await signServiceToken(session);
  const upstream = await fetch(`${env.ENGINE_URL}/v1/runs/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (upstream.status === 204) return new Response(null, { status: 204 });
  return Response.json(await upstream.json().catch(() => ({})), { status: upstream.status });
}
