import { DocumentsPanel } from "@/components/documents/documents-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";

export default function DocsPage() {
  return (
    <WorkspaceShell title="Docs">
      <DocumentsPanel />
    </WorkspaceShell>
  );
}
