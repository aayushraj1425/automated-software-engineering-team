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
  const upstream = await fetch(
    `${env.ENGINE_URL}/v1/runs/${encodeURIComponent(id)}/diff`,
    { headers: { authorization: `Bearer ${token}` }, cache: "no-store" },
  );
  return Response.json(await upstream.json(), { status: upstream.status });
}
