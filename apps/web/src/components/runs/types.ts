export type RunSummary = {
  id: string;
  status: string;
  request: string;
  repository_url: string;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type RunTask = {
  id: string;
  sequence: number;
  role: string;
  title: string;
  description: string | null;
  status: string;
  depends_on: string[];
  result: string | null;
  attempts: number;
};

export type RunDetail = RunSummary & {
  plan: { summary?: string; tasks?: string[] } | null;
  tasks: RunTask[];
};

export type RunEvent = {
  id: number;
  type: string;
  agent: string | null;
  task_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export const FINISHED_STATUSES = new Set(["completed", "failed", "cancelled"]);
