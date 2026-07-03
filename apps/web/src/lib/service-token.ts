import { SignJWT } from "jose";

import { env } from "@/lib/env";

const secret = new TextEncoder().encode(env.ENGINE_SERVICE_SECRET);

/** Short-lived HS256 JWT asserting the acting user to the engine (ADR-0002). */
export async function signServiceToken(userId: string, orgId?: string): Promise<string> {
  return new SignJWT(orgId ? { org: orgId } : {})
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(userId)
    .setIssuedAt()
    .setExpirationTime("60s")
    .sign(secret);
}
