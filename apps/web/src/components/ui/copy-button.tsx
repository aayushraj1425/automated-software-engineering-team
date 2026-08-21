"use client";

import { useState } from "react";

import { focusRing } from "./focus-ring";

/** A small copy-to-clipboard button that flips to "Copied" for a moment. Shared
 * by chat code blocks and the run diff viewer so "copy, don't paste-wrestle" is
 * consistent wherever code appears. Fails quietly when the clipboard is
 * unavailable (insecure context or blocked permission). */
export function CopyButton({
  text,
  label = "Copy",
  className = "",
}: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      aria-label={copied ? "Copied" : label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        } catch {
          // clipboard unavailable — nothing useful to do
        }
      }}
      className={`rounded border border-zinc-700 px-2 py-0.5 text-xs text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200 ${focusRing} ${className}`}
    >
      {copied ? "Copied" : label}
    </button>
  );
}
