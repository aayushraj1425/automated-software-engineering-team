import { KnowledgePanel } from "@/components/knowledge/knowledge-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";
import { requireSession } from "@/lib/require-session";

export const dynamic = "force-dynamic";

export default async function KnowledgePage() {
  await requireSession();
  return (
    <WorkspaceShell title="Knowledge">
      <KnowledgePanel />
    </WorkspaceShell>
  );
}
