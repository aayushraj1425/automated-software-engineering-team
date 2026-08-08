import { RepositoriesPanel } from "@/components/repositories/repositories-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";
import { requireSession } from "@/lib/require-session";

export const dynamic = "force-dynamic";

export default async function RepositoriesPage() {
  await requireSession();
  return (
    <WorkspaceShell title="Repositories">
      <RepositoriesPanel />
    </WorkspaceShell>
  );
}
