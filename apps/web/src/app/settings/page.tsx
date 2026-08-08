import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { IntegrationsPanel } from "@/components/settings/integrations-panel";
import { OrganizationsPanel } from "@/components/settings/organizations-panel";
import { ProviderKeysPanel } from "@/components/settings/provider-keys-panel";
import { AppNav } from "@/components/ui/app-nav";
import { auth } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) {
    redirect("/sign-in");
  }
  return (
    <div className="min-h-screen">
      <AppNav />
      <main>
        <div className="border-b border-zinc-800 px-6 py-4">
          <h1 className="text-lg font-semibold tracking-tight">Settings</h1>
        </div>
        <OrganizationsPanel />
        <ProviderKeysPanel />
        <IntegrationsPanel />
      </main>
    </div>
  );
}
