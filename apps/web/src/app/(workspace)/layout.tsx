import type { ReactNode } from "react";

import { MAIN_CONTENT_ID } from "@/components/ui/main-content";
import { requireSession } from "@/lib/require-session";

// Every route in this group is a signed-in workspace page: it needs a live
// session and a fresh per-request render. Guarding here means a new page is
// protected the moment it joins the group — it can't ship having forgotten the
// redirect — and the getSession/redirect no longer repeats in every page file.
// `dynamic` cascades to all nested pages, so they no longer declare it either.
export const dynamic = "force-dynamic";

export default async function WorkspaceLayout({ children }: { children: ReactNode }) {
  await requireSession();
  return (
    <>
      {/* One skip link for the whole signed-in app. Every workspace page renders
          an element with id="main-content" (the WorkspaceShell <main>, or chat's
          own <section>), so this moves keyboard focus to the page body wherever
          you are. Hidden until focused (Tab from the top), then shown. */}
      <a
        href={`#${MAIN_CONTENT_ID}`}
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-20 focus:rounded-md focus:bg-zinc-100 focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:text-zinc-900"
      >
        Skip to content
      </a>
      {children}
    </>
  );
}
