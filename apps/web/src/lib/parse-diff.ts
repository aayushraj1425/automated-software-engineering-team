export interface DiffFile {
  /** Path for the section header — the new path, or the old path for a deletion. */
  path: string;
  /** This file's slice of the unified diff (its `diff --git` block). */
  body: string;
  additions: number;
  deletions: number;
}

/** Split a `git diff` into one section per file, so the run page can show each
 * file collapsibly instead of as one long blob. Each file starts with a
 * `diff --git a/… b/…` line; any preamble before the first such line (rare) is
 * kept as its own section so nothing is dropped. Additions/deletions count the
 * `+`/`-` content lines, ignoring the `+++`/`---` headers. Design note:
 * docs/architecture/runs-ui/AGENT_TIMELINE_LEGIBILITY.md. */
export function parseUnifiedDiff(diff: string): DiffFile[] {
  if (!diff || diff.trim() === "") return [];
  const files: DiffFile[] = [];
  let current: string[] | null = null;

  const flush = () => {
    if (!current) return;
    files.push({ path: pathOf(current), body: current.join("\n"), ...counts(current) });
    current = null;
  };

  for (const line of diff.split("\n")) {
    if (line.startsWith("diff --git ")) {
      flush();
      current = [line];
    } else {
      (current ??= []).push(line);
    }
  }
  flush();
  return files;
}

function pathOf(lines: string[]): string {
  for (const line of lines) {
    if (line.startsWith("+++ b/")) return line.slice(6);
    if (line.startsWith("+++ ") && line.slice(4) !== "/dev/null") return line.slice(4);
  }
  // A deletion or binary file has no new path — read it off the `diff --git` header.
  const header = lines[0] ?? "";
  return header.match(/ b\/(.+)$/)?.[1] ?? header.match(/ a\/(.+?) b\//)?.[1] ?? "changes";
}

function counts(lines: string[]): { additions: number; deletions: number } {
  let additions = 0;
  let deletions = 0;
  for (const line of lines) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) additions++;
    else if (line.startsWith("-")) deletions++;
  }
  return { additions, deletions };
}
