import { PlanningBoard } from "@/components/planning/planning-board";
import { WorkspaceShell } from "@/components/ui/workspace-shell";
import { requireSession } from "@/lib/require-session";

export const dynamic = "force-dynamic";

export default async function PlanningPage() {
  await requireSession();
  return (
    <WorkspaceShell title="Planning">
      <PlanningBoard />
    </WorkspaceShell>
  );
}
