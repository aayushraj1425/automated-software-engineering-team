import { RepositoriesPanel } from "@/components/repositories/repositories-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";

export default function RepositoriesPage() {
  return (
    <WorkspaceShell title="Repositories">
      <RepositoriesPanel />
    </WorkspaceShell>
  );
}
