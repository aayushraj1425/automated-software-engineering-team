import { PlanningBoard } from "@/components/planning/planning-board";
import { WorkspaceShell } from "@/components/ui/workspace-shell";

export default function PlanningPage() {
  return (
    <WorkspaceShell title="Planning">
      <PlanningBoard />
    </WorkspaceShell>
  );
}
