import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { RunDetailPanel } from "@/components/runs/run-detail-panel";
import { auth } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) {
    redirect("/sign-in");
  }
  const { id } = await params;
  return (
    <main className="min-h-screen">
      <div className="border-b border-zinc-800 px-6 py-4">
        <h1 className="text-sm font-semibold tracking-wide">
          Run detail{" "}
          <Link href="/runs" className="ml-3 font-normal text-zinc-500 hover:text-zinc-300">
            ← all runs
          </Link>
        </h1>
      </div>
      <RunDetailPanel runId={id} />
    </main>
  );
}
