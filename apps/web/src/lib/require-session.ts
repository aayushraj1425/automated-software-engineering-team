import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { auth, type Session } from "@/lib/auth";

/** The server-side auth guard every signed-in page shares: return the active
 * session, or redirect to /sign-in when there isn't one. The (workspace) layout
 * calls this to gate the whole group; a page that also needs the session value
 * (chat, for the user's name) calls it again. `cache` collapses those repeat
 * calls within one request to a single getSession, so the layout guard is free. */
export const requireSession = cache(async (): Promise<Session> => {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) {
    redirect("/sign-in");
  }
  return session;
});
