import { IntegrationsPanel } from "@/components/settings/integrations-panel";
import { OrganizationsPanel } from "@/components/settings/organizations-panel";
import { ProviderKeysPanel } from "@/components/settings/provider-keys-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";
import { requireSession } from "@/lib/require-session";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  await requireSession();
  return (
    <WorkspaceShell title="Settings">
      <OrganizationsPanel />
      <ProviderKeysPanel />
      <IntegrationsPanel />
    </WorkspaceShell>
  );
}
