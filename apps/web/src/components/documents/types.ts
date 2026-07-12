export const DOCUMENT_KINDS = [
  "readme",
  "api_reference",
  "changelog",
  "architecture",
] as const;
export type DocumentKind = (typeof DOCUMENT_KINDS)[number];

/** Human labels for the kind chips and the generate menu. */
export const DOCUMENT_KIND_LABELS: Record<DocumentKind, string> = {
  readme: "README",
  api_reference: "API reference",
  changelog: "Changelog",
  architecture: "Architecture",
};

export type GeneratedDocument = {
  id: string;
  repository_id: string;
  kind: DocumentKind;
  title: string;
  content: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
};

export type RepositoryOption = {
  id: string;
  url: string;
};
