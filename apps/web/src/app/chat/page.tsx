import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { ChatPanel } from "@/components/chat/chat-panel";
import { auth } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function ChatPage() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) {
    redirect("/sign-in");
  }
  return <ChatPanel userName={session.user.name ?? session.user.email} />;
}
