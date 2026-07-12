import { auth } from "@/lib/auth";
import { env } from "@/lib/env";
import { signServiceToken } from "@/lib/service-token";

export const dynamic = "force-dynamic";

export async function POST(
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
    `${env.ENGINE_URL}/v1/integrations/${encodeURIComponent(kind)}/test`,
    { method: "POST", headers: { authorization: `Bearer ${token}` } },
  );
  return Response.json(await upstream.json(), { status: upstream.status });
}
