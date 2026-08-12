import Link from "next/link";

import { RunDetailPanel } from "@/components/runs/run-detail-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";

export default async function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <WorkspaceShell
      title="Run detail"
      action={
        <Link href="/runs" className="text-sm text-zinc-400 transition-colors hover:text-zinc-200">
          ← All runs
        </Link>
      }
    >
      {/* key by id so navigating between runs mounts a fresh panel — local
          state (events, diff, files, in-flight flags) never bleeds across runs. */}
      <RunDetailPanel key={id} runId={id} />
    </WorkspaceShell>
  );
}
