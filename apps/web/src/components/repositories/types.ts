export type RepositorySummary = {
  id: string;
  url: string;
  status: string;
  status_detail: string | null;
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

export type GraphNode = {
  path: string;
  language: string;
  in_degree: number;
  out_degree: number;
};

export type GraphEdge = {
  source: string;
  target: string;
};

export type DependencyGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};
