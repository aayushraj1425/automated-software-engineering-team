"use client";

import { Highlight, themes } from "prism-react-renderer";
import { useState } from "react";

import { focusRing } from "../ui/focus-ring";
import { CopyButton } from "../ui/copy-button";

const COLLAPSE_LINES = 16;

/** A fenced code block: a header with the language label and a copy button,
 * Prism syntax highlighting on the dark theme, and a collapse for long blocks so
 * a big snippet doesn't bury the prose. Design note:
 * docs/architecture/chat/CHAT_MESSAGE_RENDERING.md. */
export function CodeBlock({ code, language }: { code: string; language: string }) {
  const lines = code.split("\n");
  const long = lines.length > COLLAPSE_LINES;
  const [open, setOpen] = useState(!long);
  const shown = open ? code : lines.slice(0, COLLAPSE_LINES).join("\n");

  return (
    <div className="my-2 overflow-hidden rounded-md border border-zinc-800">
      <div className="flex items-center justify-between gap-2 bg-zinc-900/70 px-3 py-1">
        <span className="font-mono text-xs text-zinc-500">{language || "code"}</span>
        <CopyButton text={code} />
      </div>
      <Highlight code={shown} language={language || "text"} theme={themes.vsDark}>
        {({ style, tokens, getLineProps, getTokenProps }) => (
          <pre
            className="overflow-x-auto p-3 text-xs leading-5"
            style={{ ...style, background: "transparent" }}
          >
            {tokens.map((line, i) => (
              <div key={i} {...getLineProps({ line })}>
                {line.map((token, key) => (
                  <span key={key} {...getTokenProps({ token })} />
                ))}
              </div>
            ))}
          </pre>
        )}
      </Highlight>
      {long && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className={`w-full border-t border-zinc-800 bg-zinc-900/70 py-1 text-xs text-zinc-500 hover:text-zinc-300 ${focusRing}`}
        >
          {open ? "show less" : `show ${lines.length - COLLAPSE_LINES} more lines`}
        </button>
      )}
    </div>
  );
}
