import { auth } from "@/lib/auth";

/** The caller's role in their active organization (owner/admin/member), or
 * null without one. Only the destructive routes ask — the service JWT stays
 * lean everywhere else (docs/architecture/ORGANIZATION_ROLES.md). */
export async function activeOrgRole(headers: Headers): Promise<string | null> {
  try {
    const member = await auth.api.getActiveMember({ headers });
    return member?.role ?? null;
  } catch {
    return null; // no active organization — nothing to gate on
  }
}
