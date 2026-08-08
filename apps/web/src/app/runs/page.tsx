import { RunsPanel } from "@/components/runs/runs-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";
import { requireSession } from "@/lib/require-session";

export const dynamic = "force-dynamic";

export default async function RunsPage() {
  await requireSession();
  return (
    <WorkspaceShell title="Agent runs">
      <RunsPanel />
    </WorkspaceShell>
  );
}
