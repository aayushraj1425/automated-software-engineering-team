/** Save text as a downloaded file in the browser: wrap it in a Blob, click a
 * temporary link, and revoke the object URL (easy to forget, hence a helper). */
export function downloadTextFile(filename: string, text: string, type = "text/markdown"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  // The anchor must be in the document for the click to trigger a download in
  // some browsers (notably Firefox); remove it again right after.
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoke on the next tick, not synchronously: some browsers abort the
  // download if the object URL is revoked before they have read the blob.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Fetch an endpoint that returns `{ markdown, filename }` and save it as a
 * file. A no-op if the request fails — the caller need not handle the error. */
export async function downloadMarkdownFrom(url: string): Promise<void> {
  const res = await fetch(url);
  if (!res.ok) return;
  const { markdown, filename } = (await res.json()) as { markdown: string; filename: string };
  downloadTextFile(filename, markdown);
}
