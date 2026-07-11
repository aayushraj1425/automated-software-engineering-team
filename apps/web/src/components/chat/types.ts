export interface Citation {
  path: string;
  start_line: number;
  end_line: number;
  score: number;
}

/** One memory the engine recalled while answering (shown live, not persisted). */
export interface RecalledMemoryRef {
  kind: string;
  title: string;
  score: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  memories?: RecalledMemoryRef[];
  streaming?: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}
