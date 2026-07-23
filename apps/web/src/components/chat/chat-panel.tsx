"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { signOut } from "@/lib/auth-client";
import { parseSse } from "@/lib/sse";

import type { RepositorySummary } from "@/components/repositories/types";

import { Composer } from "./composer";
import { MessageList } from "./message-list";
import type { ChatMessage, Citation, ConversationSummary, RecalledMemoryRef } from "./types";

export function ChatPanel({ userName }: { userName: string }) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [repositories, setRepositories] = useState<RepositorySummary[]>([]);
  const [repositoryId, setRepositoryId] = useState<string>("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const refreshConversations = useCallback(async () => {
    const res = await fetch("/api/conversations");
    if (res.ok) setConversations(await res.json());
  }, []);

  useEffect(() => {
    void refreshConversations();
    void (async () => {
      const res = await fetch("/api/repositories");
      if (res.ok) setRepositories(await res.json());
    })();
  }, [refreshConversations]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function openConversation(id: string) {
    setConversationId(id);
    const res = await fetch(`/api/conversations/${id}/messages`);
    if (res.ok) {
      const rows: {
        id: string;
        role: "user" | "assistant";
        content: string;
        citations: Citation[] | null;
      }[] = await res.json();
      setMessages(
        rows.map((r) => ({
          id: r.id,
          role: r.role,
          content: r.content,
          citations: r.citations ?? undefined,
        })),
      );
    }
  }

  function newConversation() {
    setConversationId(null);
    setMessages([]);
  }

  async function renameConversation(id: string, currentTitle: string) {
    const next = window.prompt("Rename conversation", currentTitle);
    if (next === null) return;
    const title = next.trim();
    if (!title) return;
    const res = await fetch(`/api/conversations/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (res.ok) void refreshConversations();
  }

  async function deleteConversation(id: string) {
    if (!window.confirm("Delete this conversation and its messages?")) return;
    const res = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
    if (res.ok) {
      if (id === conversationId) newConversation();
      void refreshConversations();
    }
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
          repository_id: repositoryId || undefined,
        }),
      });
      if (!res.ok || !res.body) {
        throw new Error(`Request failed (${res.status})`);
      }
      for await (const { event, data } of parseSse(res.body)) {
        if (event === "citations") {
          const citations = (data.citations ?? []) as Citation[];
          setMessages((prev) =>
            prev.map((m) => (m.id === draftId ? { ...m, citations } : m)),
          );
        } else if (event === "memory") {
          const memories = (data.memories ?? []) as RecalledMemoryRef[];
          setMessages((prev) =>
            prev.map((m) => (m.id === draftId ? { ...m, memories } : m)),
          );
        } else if (event === "token") {
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
            <div
              key={c.id}
              className={`group flex items-center rounded-md ${
                c.id === conversationId ? "bg-zinc-800" : "hover:bg-zinc-900"
              }`}
            >
              <button
                onClick={() => void openConversation(c.id)}
                className="block flex-1 truncate px-3 py-2 text-left text-sm"
              >
                {c.title ?? "Untitled"}
              </button>
              <div className="flex shrink-0 items-center gap-1 pr-2 opacity-0 group-hover:opacity-100">
                <button
                  type="button"
                  title="Rename"
                  aria-label="Rename conversation"
                  onClick={() => void renameConversation(c.id, c.title ?? "")}
                  className="px-1 text-xs text-zinc-500 hover:text-zinc-200"
                >
                  ✎
                </button>
                <button
                  type="button"
                  title="Delete"
                  aria-label="Delete conversation"
                  onClick={() => void deleteConversation(c.id)}
                  className="px-1 text-xs text-zinc-500 hover:text-red-400"
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </nav>
        <Link
          href="/runs"
          className="mx-3 rounded-md px-3 py-2 text-left text-sm text-zinc-400 hover:bg-zinc-900"
        >
          Agent runs →
        </Link>
        <Link
          href="/docs"
          className="mx-3 rounded-md px-3 py-2 text-left text-sm text-zinc-400 hover:bg-zinc-900"
        >
          Docs →
        </Link>
        <Link
          href="/settings"
          className="mx-3 rounded-md px-3 py-2 text-left text-sm text-zinc-400 hover:bg-zinc-900"
        >
          Settings →
        </Link>
        <button
          onClick={() => void signOut({ fetchOptions: { onSuccess: () => location.assign("/") } })}
          className="m-3 rounded-md px-3 py-2 text-left text-sm text-zinc-500 hover:bg-zinc-900"
        >
          Sign out
        </button>
      </aside>
      <section className="flex flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-zinc-800 px-6 py-3">
          <label htmlFor="chat-repository" className="text-xs text-zinc-500">
            Answer from
          </label>
          <select
            id="chat-repository"
            value={repositoryId}
            onChange={(e) => setRepositoryId(e.target.value)}
            className="max-w-md truncate rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-xs text-zinc-300 outline-none focus:border-zinc-500"
          >
            <option value="">No repository — general chat</option>
            {repositories.map((repo) => (
              <option key={repo.id} value={repo.id} disabled={repo.chunks === 0}>
                {repo.url}
                {repo.chunks === 0 ? " (not indexed yet)" : ""}
              </option>
            ))}
          </select>
        </div>
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-6">
          <MessageList messages={messages} />
        </div>
        <Composer disabled={busy} onSend={(t) => void send(t)} />
      </section>
    </main>
  );
}
