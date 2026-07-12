import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { RepositoriesPanel } from "@/components/repositories/repositories-panel";
import { auth } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function RepositoriesPage() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) {
    redirect("/sign-in");
  }
  return (
    <main className="min-h-screen">
      <div className="border-b border-zinc-800 px-6 py-4">
        <h1 className="text-sm font-semibold tracking-wide">
          Repositories{" "}
          <Link href="/planning" className="ml-3 font-normal text-zinc-500 hover:text-zinc-300">
            planning
          </Link>{" "}
          <Link href="/runs" className="ml-3 font-normal text-zinc-500 hover:text-zinc-300">
            agent runs
          </Link>{" "}
          <Link href="/knowledge" className="ml-3 font-normal text-zinc-500 hover:text-zinc-300">
            knowledge
          </Link>{" "}
          <Link href="/docs" className="ml-3 font-normal text-zinc-500 hover:text-zinc-300">
            docs
          </Link>{" "}
          <Link href="/chat" className="ml-3 font-normal text-zinc-500 hover:text-zinc-300">
            chat
          </Link>{" "}
          <Link href="/settings" className="ml-3 font-normal text-zinc-500 hover:text-zinc-300">
            settings
          </Link>
        </h1>
      </div>
      <RepositoriesPanel />
    </main>
  );
}
