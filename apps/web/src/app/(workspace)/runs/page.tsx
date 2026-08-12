import { RunsPanel } from "@/components/runs/runs-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";

export default function RunsPage() {
  return (
    <WorkspaceShell title="Agent runs">
      <RunsPanel />
    </WorkspaceShell>
  );
}
