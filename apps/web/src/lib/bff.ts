import { auth } from "@/lib/auth";
import { env } from "@/lib/env";
import { signServiceToken } from "@/lib/service-token";

export type ProxyOptions = {
  /** HTTP method to send to the engine. Defaults to GET. */
  method?: string;
  /** Read the request's JSON body and forward it verbatim; an unreadable body
   * is a 400 before the engine is called. Omit for a bodyless call. */
  forwardBody?: boolean;
  /** The caller's organization role, signed into the token only by the
   * destructive routes that gate on it (docs/architecture/ORGANIZATION_ROLES.md);
   * omitted everywhere else so the token stays lean. */
  orgRole?: string | null;
};

/** The Backend-for-Frontend proxy every `/api/*` route repeats: authenticate
 * the browser session, sign a short-lived service JWT (ADR-0002), forward the
 * call to the engine, and relay the engine's status and JSON body back.
 *
 * `path` is the engine path starting at `/v1/…`; the caller encodes any dynamic
 * segment and query string. Returns the uniform 401 with no session, 400 on an
 * unreadable JSON body when `forwardBody` is set, and a bodyless 204 straight
 * through. Streaming routes (chat, the run event stream) and the better-auth
 * handler don't fit this shape and stay hand-written.
 * Design note: docs/architecture/BFF_PROXY.md. */
export async function proxyToEngine(
  req: Request,
  path: string,
  options: ProxyOptions = {},
): Promise<Response> {
  const session = await auth.api.getSession({ headers: req.headers });
  if (!session) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const headers: Record<string, string> = {};
  let body: string | undefined;
  if (options.forwardBody) {
    let parsed: unknown;
    try {
      parsed = await req.json();
    } catch {
      return Response.json({ error: "Invalid JSON body" }, { status: 400 });
    }
    body = JSON.stringify(parsed);
    headers["content-type"] = "application/json";
  }

  const token = await signServiceToken(session, { orgRole: options.orgRole });
  headers.authorization = `Bearer ${token}`;

  const upstream = await fetch(`${env.ENGINE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body,
    cache: "no-store",
  });

  if (upstream.status === 204) {
    return new Response(null, { status: 204 });
  }
  return Response.json(await upstream.json().catch(() => ({})), { status: upstream.status });
}
