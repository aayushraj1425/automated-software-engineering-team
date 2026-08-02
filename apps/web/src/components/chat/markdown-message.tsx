"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { CodeBlock } from "./code-block";

/** react-markdown wraps block code in <pre>; we render our own CodeBlock, so
 * make <pre> a passthrough and detect block vs inline in the code renderer. */
const components: Components = {
  pre: ({ children }) => <>{children}</>,
  code({ className, children }) {
    const text = String(children ?? "");
    const language = /language-(\w+)/.exec(className ?? "")?.[1];
    // Block code either carries a language class or spans multiple lines.
    if (language || text.includes("\n")) {
      return <CodeBlock code={text.replace(/\n$/, "")} language={language ?? ""} />;
    }
    return (
      <code className="rounded bg-zinc-800 px-1 py-0.5 font-mono text-[0.85em] text-zinc-200">
        {children}
      </code>
    );
  },
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-sky-400 underline hover:text-sky-300"
    >
      {children}
    </a>
  ),
  h1: ({ children }) => <h1 className="text-base font-semibold text-zinc-100">{children}</h1>,
  h2: ({ children }) => <h2 className="text-sm font-semibold text-zinc-100">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold text-zinc-200">{children}</h3>,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-zinc-700 pl-3 text-zinc-400">{children}</blockquote>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-zinc-800 px-2 py-1 text-left text-zinc-300">{children}</th>
  ),
  td: ({ children }) => (
    <td className="border border-zinc-800 px-2 py-1 text-zinc-400">{children}</td>
  ),
};

/** Render an assistant reply as Markdown — GFM tables/lists/links styled for the
 * dark theme, fenced code as a CodeBlock (highlight + copy + collapse), inline
 * code as a small styled span. Design note:
 * docs/architecture/chat/CHAT_MESSAGE_RENDERING.md. */
export function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="space-y-2 text-sm leading-6">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
