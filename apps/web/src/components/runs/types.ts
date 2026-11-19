import type { EngineApiComponents } from "@asep/shared";

export type RunSummary = {
  id: string;
  status: string;
  request: string;
  repository_url: string;
  error: string | null;
  pr_url: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  complexity?: "quick" | "standard" | "complex" | null;
  triage_reason?: string | null;
  team_template?: string;
  test_only?: boolean;
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
  /** The seat level and model the engine persisted for this task. */
  level?: string;
  model?: string | null;
};

/** One seat on a run's team. `key` is `role:level`. */
export type TeamSeat = {
  key: string;
  role: string;
  level: string;
  model?: string | null;
  reason: string;
};

/** One entry of the engine's model catalog (`GET /v1/models`). */
export type CatalogModel = {
  id: string;
  provider: string;
  context_size: number;
  supports_tools: boolean;
  strength: number;
  input_cost_per_million: number;
  output_cost_per_million: number;
  open_source: boolean;
  evaluated: boolean;
};

export type RunDetail = RunSummary & {
  plan: { summary?: string; tasks?: string[] } | null;
  tasks: RunTask[];
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  test_report?: {
    status: string;
    reason: string;
    output: string;
    test_command: string | null;
    scope: string;
  } | null;
  team?: TeamSeat[];
  model_overrides?: Record<string, string>;
  design_note?: string | null;
  stages_completed?: string[];
  preview_requested?: boolean | null;
  preview_options?: EngineApiComponents["schemas"]["PreviewOptions"] | null;
  deployment_source_sha?: string | null;
  /** Read defensively through `parsePreview` for older or incomplete records. */
  preview_deployment?: Record<string, unknown> | null;
  deployment_status?: string;
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

export type WorkspaceFile = {
  path: string;
  size: number;
};
