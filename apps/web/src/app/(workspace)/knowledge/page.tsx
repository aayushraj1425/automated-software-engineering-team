import { KnowledgePanel } from "@/components/knowledge/knowledge-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";

export default function KnowledgePage() {
  return (
    <WorkspaceShell title="Knowledge">
      <KnowledgePanel />
    </WorkspaceShell>
  );
}
