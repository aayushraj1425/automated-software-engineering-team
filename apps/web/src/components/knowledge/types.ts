export const KNOWLEDGE_KINDS = ["note", "preference", "decision", "outcome"] as const;
export type KnowledgeKind = (typeof KNOWLEDGE_KINDS)[number];

/** Kinds a person can write by hand; decisions and outcomes are captured by runs. */
export const MANUAL_KINDS = ["note", "preference"] as const;

export type KnowledgeItem = {
  id: string;
  repository_id: string;
  kind: KnowledgeKind;
  title: string;
  content: string;
  source_run_id: string | null;
  created_by: string | null;
  created_at: string;
  score: number | null;
};

export type RepositoryOption = {
  id: string;
  url: string;
};
