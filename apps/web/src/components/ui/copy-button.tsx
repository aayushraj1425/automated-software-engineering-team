"use client";

import { focusRing } from "./focus-ring";
import { useCopyFeedback } from "./use-copy-feedback";

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
  const { copied, copy } = useCopyFeedback();

  return (
    <>
      <button
        type="button"
        aria-label={copied ? "Copied" : label}
        onClick={() => void copy(text)}
        className={`rounded border border-zinc-700 px-2 py-0.5 text-xs text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200 ${focusRing} ${className}`}
      >
        {copied ? "Copied" : label}
      </button>
      {/* A sibling live region (not nested in the button, which would muddy its
          name): announced to screen readers on copy, since the visible label
          swap alone isn't reliably re-read while focus stays on the button. */}
      <span role="status" className="sr-only">
        {copied ? "Copied to clipboard" : ""}
      </span>
    </>
  );
}
