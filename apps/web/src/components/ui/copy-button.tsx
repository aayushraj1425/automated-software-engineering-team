"use client";

import { useEffect, useRef, useState } from "react";

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
  // One pending "flip back" timer, held so a rapid re-click restarts it instead
  // of stacking timers (an earlier one would otherwise flip "Copied" back while
  // the latest click still wants it shown), and so it's cancelled on unmount
  // rather than setting state on a gone component.
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <>
      <button
        type="button"
        aria-label={copied ? "Copied" : label}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            clearTimeout(timer.current);
            timer.current = setTimeout(() => setCopied(false), 1200);
          } catch {
            // clipboard unavailable — nothing useful to do
          }
        }}
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
