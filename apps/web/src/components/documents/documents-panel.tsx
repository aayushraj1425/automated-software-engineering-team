"use client";

import { useCallback, useEffect, useState } from "react";

import {
  DOCUMENT_KINDS,
  DOCUMENT_KIND_LABELS,
  type DocumentKind,
  type GeneratedDocument,
  type RepositoryOption,
} from "./types";

/** Generate and read a repository's documentation: pick a kind, generate it
 * from the index, then browse, read, and delete the results. */
export function DocumentsPanel() {
  const [repositories, setRepositories] = useState<RepositoryOption[]>([]);
  const [repositoryId, setRepositoryId] = useState<string | null>(null);
  const [documents, setDocuments] = useState<GeneratedDocument[]>([]);
  const [kind, setKind] = useState<DocumentKind>("readme");
  const [openId, setOpenId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void (async () => {
      const res = await fetch("/api/repositories");
      if (!res.ok) return;
      const repos: RepositoryOption[] = await res.json();
      setRepositories(repos);
      setRepositoryId((current) => current ?? repos[0]?.id ?? null);
    })();
  }, []);

  const refresh = useCallback(async () => {
    if (!repositoryId) return;
    const res = await fetch(`/api/repositories/${repositoryId}/documents`);
    if (res.ok) setDocuments(await res.json());
  }, [repositoryId]);

  useEffect(() => {
    setOpenId(null);
    void refresh();
  }, [refresh]);

  async function generate() {
    if (!repositoryId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/repositories/${repositoryId}/documents`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind }),
      });
      if (!res.ok) throw new Error(`Could not generate the document (${res.status})`);
      const created: GeneratedDocument = await res.json();
      await refresh();
      setOpenId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  function startEditing(doc: GeneratedDocument) {
    setEditingId(doc.id);
    setDraft(doc.content);
    setOpenId(doc.id);
  }

  async function saveEdit(id: string) {
    if (!repositoryId || !draft.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`/api/repositories/${repositoryId}/documents/${id}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ content: draft }),
      });
      if (!res.ok) throw new Error(`Could not save the document (${res.status})`);
      setEditingId(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    if (!repositoryId) return;
    const res = await fetch(`/api/repositories/${repositoryId}/documents/${id}`, {
      method: "DELETE",
    });
    setError(res.ok ? null : `Could not delete the document (${res.status})`);
    if (openId === id) setOpenId(null);
    await refresh();
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <section className="space-y-3">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-zinc-300">Repository</h2>
          <select
            value={repositoryId ?? ""}
            onChange={(e) => setRepositoryId(e.target.value || null)}
            className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs outline-none focus:border-zinc-500"
          >
            {repositories.length === 0 && <option value="">No repositories connected</option>}
            {repositories.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.url}
              </option>
            ))}
          </select>
        </div>
        <p className="text-xs text-zinc-500">
          The Technical Writer reads the repository index and writes documentation about it.
          Index the repository first so the writer has code to describe.
        </p>
      </section>

      {repositoryId && (
        <section className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold text-zinc-300">Generate a document</h2>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as DocumentKind)}
            className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs outline-none focus:border-zinc-500"
          >
            {DOCUMENT_KINDS.map((k) => (
              <option key={k} value={k}>
                {DOCUMENT_KIND_LABELS[k]}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void generate()}
            disabled={busy}
            className="rounded-md bg-zinc-100 px-4 py-1.5 text-sm font-medium text-zinc-900 disabled:opacity-50"
          >
            {busy ? "Writing…" : "Generate"}
          </button>
          {error && <p className="w-full text-sm text-red-400">{error}</p>}
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Documents</h2>
        {repositoryId && documents.length === 0 && (
          <p className="text-sm text-zinc-500">
            No documents yet. Pick a type above and generate the first one.
          </p>
        )}
        {documents.map((doc) => (
          <div key={doc.id} className="space-y-3 rounded-md border border-zinc-800 p-4">
            <div className="flex items-start justify-between gap-3">
              <button
                type="button"
                onClick={() => setOpenId((current) => (current === doc.id ? null : doc.id))}
                className="text-left text-sm text-zinc-200 hover:text-white"
              >
                {doc.title}
              </button>
              <div className="flex shrink-0 items-center gap-3">
                <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs font-medium text-zinc-400">
                  {DOCUMENT_KIND_LABELS[doc.kind]}
                </span>
                <button
                  type="button"
                  onClick={() => void remove(doc.id)}
                  className="text-xs text-zinc-600 hover:text-red-400"
                  title="Delete this document"
                >
                  delete
                </button>
              </div>
            </div>
            <div className="flex items-center gap-3 text-xs text-zinc-600">
              <span>{new Date(doc.created_at).toLocaleString()}</span>
              <button
                type="button"
                onClick={() => setOpenId((current) => (current === doc.id ? null : doc.id))}
                className="text-zinc-500 hover:text-zinc-300"
              >
                {openId === doc.id ? "hide" : "read"}
              </button>
              {editingId !== doc.id && (
                <button
                  type="button"
                  onClick={() => startEditing(doc)}
                  className="text-zinc-500 hover:text-zinc-300"
                  title="Correct the document where the model got it wrong"
                >
                  edit
                </button>
              )}
            </div>
            {openId === doc.id && editingId === doc.id ? (
              <div className="space-y-2">
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  spellCheck={false}
                  className="h-80 w-full rounded-md border border-zinc-800 bg-zinc-950 p-4 font-mono text-xs leading-5 text-zinc-300 outline-none focus:border-zinc-600"
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void saveEdit(doc.id)}
                    disabled={saving || !draft.trim()}
                    className="rounded-md bg-zinc-100 px-3 py-1.5 text-xs font-medium text-zinc-900 disabled:opacity-50"
                  >
                    {saving ? "Saving…" : "Save"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditingId(null)}
                    disabled={saving}
                    className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-400 disabled:opacity-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              openId === doc.id && (
                <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-md bg-zinc-950 p-4 text-xs text-zinc-300">
                  {doc.content}
                </pre>
              )
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
