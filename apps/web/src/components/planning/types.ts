export type WorkItemKind = "feature" | "bug" | "chore" | "spike";
export type WorkItemStatus =
  "proposed" | "ready" | "in_progress" | "blocked" | "done" | "cancelled";
export type Estimate = "small" | "medium" | "large";
export type Priority = "low" | "medium" | "high" | "critical";

export type WorkItem = {
  id: string;
  repository_id: string;
  title: string;
  description: string | null;
  kind: WorkItemKind;
  status: WorkItemStatus;
  estimate: Estimate | null;
  priority: Priority;
  milestone: string | null;
  depends_on: string[];
  rationale: string | null;
  position: number;
  implemented_by_run_id: string | null;
  external_issue_url: string | null;
  external_issue_key: string | null;
  created_at: string;
  updated_at: string;
};

export type RepositoryOption = {
  id: string;
  url: string;
};

export type BlockedItem = {
  item_id: string;
  title: string;
  waiting_on: string[];
};

export type PlanInsights = {
  blocked: BlockedItem[];
  recommended: WorkItem | null;
};

export const KINDS: WorkItemKind[] = ["feature", "bug", "chore", "spike"];
export const STATUSES: WorkItemStatus[] = [
  "proposed",
  "ready",
  "in_progress",
  "blocked",
  "done",
  "cancelled",
];
export const ESTIMATES: Estimate[] = ["small", "medium", "large"];
export const PRIORITIES: Priority[] = ["low", "medium", "high", "critical"];
