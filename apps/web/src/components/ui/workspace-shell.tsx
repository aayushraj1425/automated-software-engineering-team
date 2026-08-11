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
      {/* Keyboard users can jump straight past the nav to the page body. Hidden
          until focused (Tab from the top of the page), then shown. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-20 focus:rounded-md focus:bg-zinc-100 focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:text-zinc-900"
      >
        Skip to content
      </a>
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
