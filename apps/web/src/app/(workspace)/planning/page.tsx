import { PlanningBoard } from "@/components/planning/planning-board";
import { WorkspaceShell } from "@/components/ui/workspace-shell";

export const metadata = { title: "Planning" };

export default function PlanningPage() {
  return (
    <WorkspaceShell title="Planning">
      <PlanningBoard />
    </WorkspaceShell>
  );
}
