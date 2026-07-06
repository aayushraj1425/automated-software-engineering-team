export type RepositorySummary = {
  id: string;
  url: string;
  status: string;
  default_branch: string;
  last_indexed_at: string | null;
  chunks: number;
};

export type SearchHit = {
  path: string;
  language: string;
  start_line: number;
  end_line: number;
  snippet: string;
  score: number;
};
