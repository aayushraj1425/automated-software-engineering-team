import { ChatPanel } from "@/components/chat/chat-panel";
import { requireSession } from "@/lib/require-session";

export const metadata = { title: "Chat" };

export default async function ChatPage() {
  const session = await requireSession();
  return <ChatPanel userName={session.user.name ?? session.user.email} />;
}
