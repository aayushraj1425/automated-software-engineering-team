import { auth } from "@/lib/auth";
import { env } from "@/lib/env";
import { signServiceToken } from "@/lib/service-token";

export const dynamic = "force-dynamic";

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ kind: string }> },
): Promise<Response> {
  const session = await auth.api.getSession({ headers: req.headers });
  if (!session) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const { kind } = await params;
  const token = await signServiceToken(session.user.id);
  const upstream = await fetch(
    `${env.ENGINE_URL}/v1/integrations/${encodeURIComponent(kind)}`,
    {
      method: "PUT",
      headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    },
  );
  return Response.json(await upstream.json(), { status: upstream.status });
}

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ kind: string }> },
): Promise<Response> {
  const session = await auth.api.getSession({ headers: req.headers });
  if (!session) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { kind } = await params;
  const token = await signServiceToken(session.user.id);
  const upstream = await fetch(
    `${env.ENGINE_URL}/v1/integrations/${encodeURIComponent(kind)}`,
    { method: "DELETE", headers: { authorization: `Bearer ${token}` } },
  );
  if (upstream.status === 204) {
    return new Response(null, { status: 204 });
  }
  return Response.json(await upstream.json(), { status: upstream.status });
}
