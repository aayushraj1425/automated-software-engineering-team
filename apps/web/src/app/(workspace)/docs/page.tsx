import { DocumentsPanel } from "@/components/documents/documents-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";

export const metadata = { title: "Docs" };

export default function DocsPage() {
  return (
    <WorkspaceShell title="Docs">
      <DocumentsPanel />
    </WorkspaceShell>
  );
}
