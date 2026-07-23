import { auth } from "@/lib/auth";
import { env } from "@/lib/env";
import { signServiceToken } from "@/lib/service-token";

export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const session = await auth.api.getSession({ headers: req.headers });
  if (!session) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  const token = await signServiceToken(session);
  // Forward a ?status= filter through to the engine (only the known param).
  const status = new URL(req.url).searchParams.get("status");
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const upstream = await fetch(`${env.ENGINE_URL}/v1/runs${query}`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return Response.json(await upstream.json(), { status: upstream.status });
}

export async function POST(req: Request): Promise<Response> {
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

  const token = await signServiceToken(session);
  const upstream = await fetch(`${env.ENGINE_URL}/v1/runs`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  return Response.json(await upstream.json(), { status: upstream.status });
}
