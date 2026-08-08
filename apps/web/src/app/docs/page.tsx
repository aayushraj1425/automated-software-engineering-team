import { DocumentsPanel } from "@/components/documents/documents-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";
import { requireSession } from "@/lib/require-session";

export const dynamic = "force-dynamic";

export default async function DocsPage() {
  await requireSession();
  return (
    <WorkspaceShell title="Docs">
      <DocumentsPanel />
    </WorkspaceShell>
  );
}
