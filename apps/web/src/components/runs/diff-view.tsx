"use client";

import { useState } from "react";

import { downloadTextFile } from "@/lib/download";
import { type DiffFile, parseUnifiedDiff } from "@/lib/parse-diff";

import { CopyButton } from "../ui/copy-button";

function diffLineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "text-zinc-500";
  if (line.startsWith("+")) return "text-emerald-400";
  if (line.startsWith("-")) return "text-red-400";
  if (line.startsWith("@@")) return "text-sky-400";
  return "text-zinc-400";
}

/** The run's changes, one collapsible section per file, each with its own copy
 * button, plus a Download .diff for the whole patch — so the changes are
 * reviewable without selecting a giant blob by hand. Design note:
 * docs/architecture/runs-ui/AGENT_TIMELINE_LEGIBILITY.md. */
export function DiffView({ diff }: { diff: string }) {
  const files = parseUnifiedDiff(diff);
  if (files.length === 0) return null;

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-300">
          Changes{" "}
          <span className="text-xs font-normal text-zinc-500">
            ({files.length} file{files.length === 1 ? "" : "s"})
          </span>
        </h2>
        <button
          type="button"
          onClick={() => downloadTextFile("changes.diff", diff, "text/x-patch")}
          className="rounded border border-zinc-700 px-2 py-0.5 text-xs text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"
        >
          Download .diff
        </button>
      </div>
      <div className="space-y-2">
        {files.map((file, i) => (
          // Diffs render in a stable order; the index key is fine here.
          <FileSection key={i} file={file} defaultOpen={files.length <= 3} />
        ))}
      </div>
    </section>
  );
}

function FileSection({ file, defaultOpen }: { file: DiffFile; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="overflow-hidden rounded-md border border-zinc-800">
      <div className="flex items-center justify-between gap-2 bg-zinc-900/60 px-3 py-1.5">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex min-w-0 items-center gap-2 text-left"
        >
          <span className="shrink-0 text-zinc-500">{open ? "▾" : "▸"}</span>
          <span className="truncate font-mono text-xs text-zinc-300">{file.path}</span>
          <span className="shrink-0 text-xs">
            <span className="text-emerald-400">+{file.additions}</span>{" "}
            <span className="text-red-400">−{file.deletions}</span>
          </span>
        </button>
        <CopyButton text={file.body} />
      </div>
      {open && (
        <pre className="overflow-x-auto px-4 py-3 text-xs leading-5">
          {file.body.split("\n").map((line, index) => (
            <div key={index} className={diffLineClass(line)}>
              {line || " "}
            </div>
          ))}
        </pre>
      )}
    </div>
  );
}
