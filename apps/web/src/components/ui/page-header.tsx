import type { ReactNode } from "react";

/** The titled bar directly under the nav. One place for the heading treatment
 * so every page's header matches; `action` renders on the right for a page-level
 * control or a back link. */
export function PageHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-zinc-800 px-6 py-4">
      <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
      {action}
    </div>
  );
}
