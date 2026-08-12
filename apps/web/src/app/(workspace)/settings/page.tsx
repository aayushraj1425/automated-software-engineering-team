import { IntegrationsPanel } from "@/components/settings/integrations-panel";
import { OrganizationsPanel } from "@/components/settings/organizations-panel";
import { ProviderKeysPanel } from "@/components/settings/provider-keys-panel";
import { WorkspaceShell } from "@/components/ui/workspace-shell";

export default function SettingsPage() {
  return (
    <WorkspaceShell title="Settings">
      <OrganizationsPanel />
      <ProviderKeysPanel />
      <IntegrationsPanel />
    </WorkspaceShell>
  );
}
