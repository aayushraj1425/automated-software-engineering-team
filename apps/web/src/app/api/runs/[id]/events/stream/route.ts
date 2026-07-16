import { auth } from "@/lib/auth";
import { env } from "@/lib/env";
import { signServiceToken } from "@/lib/service-token";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** BFF proxy for the live run timeline: validate the session, sign a service
 * JWT, pipe the engine's SSE back. A reconnecting EventSource sends
 * Last-Event-ID — forwarded so the engine resumes exactly where it left off. */
export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const session = await auth.api.getSession({ headers: req.headers });
  if (!session) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const after = new URL(req.url).searchParams.get("after");
  const query = after ? `?after=${encodeURIComponent(after)}` : "";
  const token = await signServiceToken(session);
  const headers: Record<string, string> = { authorization: `Bearer ${token}` };
  const lastEventId = req.headers.get("last-event-id");
  if (lastEventId) headers["last-event-id"] = lastEventId;

  const upstream = await fetch(
    `${env.ENGINE_URL}/v1/runs/${encodeURIComponent(id)}/events/stream${query}`,
    { headers },
  );

  if (!upstream.ok || !upstream.body) {
    return Response.json({ error: `Engine error (${upstream.status})` }, { status: 502 });
  }

  return new Response(upstream.body, {
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
    },
  });
}
