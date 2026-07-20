import { SignJWT } from "jose";

import { env } from "@/lib/env";

const secret = new TextEncoder().encode(env.ENGINE_SERVICE_SECRET);

/** The slice of a better-auth session the token needs — structural, so
 * tests don't have to build a full session object. */
export type SessionForToken = {
  user: { id: string };
  session: { activeOrganizationId?: string | null };
};

/** Short-lived HS256 JWT asserting the acting user to the engine (ADR-0002).
 * The active organization (the settings-page switcher) rides along as the
 * `org` claim — the engine's Principal already parses it, and org-aware
 * sharing builds on it (docs/architecture/SIGN_IN_AND_ORGANIZATIONS.md).
 * `orgRole` is signed in only by the destructive routes that gate on it
 * (docs/architecture/ORGANIZATION_ROLES.md). */
export async function signServiceToken(
  session: SessionForToken,
  options?: { orgRole?: string | null },
): Promise<string> {
  const orgId = session.session.activeOrganizationId;
  const claims: Record<string, string> = {};
  if (orgId) claims.org = orgId;
  if (orgId && options?.orgRole) claims.org_role = options.orgRole;
  return new SignJWT(claims)
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(session.user.id)
    .setIssuedAt()
    .setExpirationTime("60s")
    .sign(secret);
}
