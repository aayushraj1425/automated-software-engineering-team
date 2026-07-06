import type { ChatMessage } from "./types";

export function MessageList({ messages }: { messages: ChatMessage[] }) {
  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-500">
        Ask ASEP about architecture, bugs, features, testing, or deployment.
      </div>
    );
  }
  return (
    <ul className="space-y-4">
      {messages.map((m) => (
        <li key={m.id} className="flex" data-role={m.role}>
          <div
            className={
              m.role === "user"
                ? "ml-auto max-w-[80%] rounded-2xl rounded-br-sm bg-zinc-100 px-4 py-2 text-sm text-zinc-900"
                : "mr-auto max-w-[80%] rounded-2xl rounded-bl-sm border border-zinc-800 bg-zinc-900 px-4 py-2 text-sm text-zinc-100"
            }
          >
            <p className="whitespace-pre-wrap">
              {m.content}
              {m.streaming && <span className="animate-pulse">▍</span>}
            </p>
            {m.citations && m.citations.length > 0 && (
              <div className="mt-2 border-t border-zinc-800 pt-2">
                <p className="mb-1 text-xs font-medium text-zinc-500">Sources</p>
                {m.citations.map((c, i) => (
                  <p key={i} className="font-mono text-xs text-zinc-500">
                    {c.path}:{c.start_line}–{c.end_line}
                    <span className="ml-2 text-zinc-600">score {c.score.toFixed(2)}</span>
                  </p>
                ))}
              </div>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
