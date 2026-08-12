import type { ReactNode } from "react";

import { AppNav } from "@/components/ui/app-nav";
import { PageHeader } from "@/components/ui/page-header";

/** The frame every signed-in workspace page shares: the top navigation, a
 * titled header, and the page body. It collapses each page file down to "guard
 * the session, name the page, render the panel", and — because the nav lives
 * here — a new page cannot ship missing it (which is how the run-detail page
 * had drifted). `action` renders beside the title, e.g. a back link. */
export function WorkspaceShell({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen">
      {/* The skip link lives in the (workspace) layout so it's shared with chat
          too; it targets the #main-content below. */}
      <AppNav />
      {/* tabIndex=-1 so activating the skip link actually moves keyboard focus
          here, not just the scroll position (some browsers won't focus a
          non-interactive target otherwise). */}
      <main id="main-content" tabIndex={-1} className="outline-none">
        <PageHeader title={title} action={action} />
        {children}
      </main>
    </div>
  );
}
