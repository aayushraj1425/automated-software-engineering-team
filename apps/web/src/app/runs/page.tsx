import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { RunsPanel } from "@/components/runs/runs-panel";
import { AppNav } from "@/components/ui/app-nav";
import { auth } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function RunsPage() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) {
    redirect("/sign-in");
  }
  return (
    <div className="min-h-screen">
      <AppNav />
      <main>
        <div className="border-b border-zinc-800 px-6 py-4">
          <h1 className="text-lg font-semibold tracking-tight">Agent runs</h1>
        </div>
        <RunsPanel />
      </main>
    </div>
  );
}
