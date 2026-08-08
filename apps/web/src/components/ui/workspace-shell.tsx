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
      <AppNav />
      <main>
        <PageHeader title={title} action={action} />
        {children}
      </main>
    </div>
  );
}
