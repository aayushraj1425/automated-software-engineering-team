"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { signOut } from "@/lib/auth-client";
import { parseSse } from "@/lib/sse";

import { Composer } from "./composer";
import { MessageList } from "./message-list";
import type { ChatMessage, ConversationSummary } from "./types";

export function ChatPanel({ userName }: { userName: string }) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const refreshConversations = useCallback(async () => {
    const res = await fetch("/api/conversations");
    if (res.ok) setConversations(await res.json());
  }, []);

  useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function openConversation(id: string) {
    setConversationId(id);
    const res = await fetch(`/api/conversations/${id}/messages`);
    if (res.ok) {
      const rows: { id: string; role: "user" | "assistant"; content: string }[] =
        await res.json();
      setMessages(rows.map((r) => ({ id: r.id, role: r.role, content: r.content })));
    }
  }

  function newConversation() {
    setConversationId(null);
    setMessages([]);
  }

  async function send(text: string) {
    setBusy(true);
    const userMsg: ChatMessage = { id: `local-${Date.now()}`, role: "user", content: text };
    const draftId = `draft-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: draftId, role: "assistant", content: "", streaming: true },
    ]);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId ?? undefined,
        }),
      });
      if (!res.ok || !res.body) {
        throw new Error(`Request failed (${res.status})`);
      }
      for await (const { event, data } of parseSse(res.body)) {
        if (event === "token") {
          const tokenText = String(data.text ?? "");
          setMessages((prev) =>
            prev.map((m) => (m.id === draftId ? { ...m, content: m.content + tokenText } : m)),
          );
        } else if (event === "done") {
          setConversationId(String(data.conversation_id));
          setMessages((prev) =>
            prev.map((m) => (m.id === draftId ? { ...m, streaming: false } : m)),
          );
        } else if (event === "error") {
          throw new Error(String(data.message ?? "Stream error"));
        }
      }
      void refreshConversations();
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === draftId
            ? {
                ...m,
                streaming: false,
                content: m.content || `⚠ ${err instanceof Error ? err.message : "Failed"}`,
              }
            : m,
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex h-screen">
      <aside className="flex w-64 flex-col border-r border-zinc-800 bg-zinc-900/40">
        <div className="border-b border-zinc-800 p-4">
          <h1 className="text-sm font-semibold tracking-wide">ASEP</h1>
          <p className="truncate text-xs text-zinc-500">{userName}</p>
        </div>
        <button
          onClick={newConversation}
          className="m-3 rounded-md border border-zinc-700 px-3 py-2 text-left text-sm hover:bg-zinc-900"
        >
          + New chat
        </button>
        <nav className="flex-1 space-y-1 overflow-y-auto px-3">
          {conversations.map((c) => (
            <button
              key={c.id}
              onClick={() => void openConversation(c.id)}
              className={`block w-full truncate rounded-md px-3 py-2 text-left text-sm ${
                c.id === conversationId ? "bg-zinc-800" : "hover:bg-zinc-900"
              }`}
            >
              {c.title ?? "Untitled"}
            </button>
          ))}
        </nav>
        <Link
          href="/runs"
          className="mx-3 rounded-md px-3 py-2 text-left text-sm text-zinc-400 hover:bg-zinc-900"
        >
          Agent runs →
        </Link>
        <button
          onClick={() => void signOut({ fetchOptions: { onSuccess: () => location.assign("/") } })}
          className="m-3 rounded-md px-3 py-2 text-left text-sm text-zinc-500 hover:bg-zinc-900"
        >
          Sign out
        </button>
      </aside>
      <section className="flex flex-1 flex-col">
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-6">
          <MessageList messages={messages} />
        </div>
        <Composer disabled={busy} onSend={(t) => void send(t)} />
      </section>
    </main>
  );
}
