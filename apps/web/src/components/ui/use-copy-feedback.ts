"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Copy-to-clipboard with a short-lived "copied" flag, done safely once so every
 * copy affordance shares it. The reset timer lives in a ref: a rapid second copy
 * restarts the window instead of stacking timers (an earlier one would otherwise
 * clear the flag while the latest copy still wants it shown), and it's cancelled
 * on unmount rather than setting state on a gone component. `copy` fails quietly
 * when the clipboard is unavailable (insecure context or blocked permission). */
export function useCopyFeedback(resetMs = 1200): {
  copied: boolean;
  copy: (text: string) => Promise<void>;
} {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), resetMs);
      } catch {
        // clipboard unavailable — nothing useful to do
      }
    },
    [resetMs],
  );

  return { copied, copy };
}
