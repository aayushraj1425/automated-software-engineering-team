import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { auth, type Session } from "@/lib/auth";

/** The server-side auth guard every signed-in page shares: return the active
 * session, or redirect to /sign-in when there isn't one. Centralizes the
 * getSession + redirect that was copy-pasted into every page, so a page can
 * only forget the guard by not calling it — not by getting it subtly wrong. */
export async function requireSession(): Promise<Session> {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) {
    redirect("/sign-in");
  }
  return session;
}
