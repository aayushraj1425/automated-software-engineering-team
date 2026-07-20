"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";

import { authClient } from "@/lib/auth-client";

/** The landing page for a copied invitation link: accept joins the
 * organization and switches into it; decline just declines. Signed-out
 * visitors are sent to sign in first — better-auth matches the invitation
 * to the signed-in email (docs/architecture/ORGANIZATION_ROLES.md). */
export default function AcceptInvitationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const { data: session, isPending } = authClient.useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function accept() {
    setBusy(true);
    setError(null);
    const { data, error } = await authClient.organization.acceptInvitation({
      invitationId: id,
    });
    setBusy(false);
    if (error) {
      setError(error.message ?? "Could not accept the invitation");
      return;
    }
    const organizationId = data?.invitation?.organizationId;
    if (organizationId) {
      await authClient.organization.setActive({ organizationId });
    }
    router.push("/chat");
  }

  async function decline() {
    setBusy(true);
    setError(null);
    const { error } = await authClient.organization.rejectInvitation({ invitationId: id });
    setBusy(false);
    if (error) {
      setError(error.message ?? "Could not decline the invitation");
      return;
    }
    router.push("/chat");
  }

  if (isPending) {
    return <main className="p-6 text-sm text-zinc-500">Loading…</main>;
  }

  if (!session) {
    return (
      <main className="mx-auto max-w-md space-y-4 p-6">
        <h1 className="text-lg font-semibold">Organization invitation</h1>
        <p className="text-sm text-zinc-400">
          Sign in with the invited email address first, then open this link again.
        </p>
        <a
          href="/sign-in"
          className="inline-block rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900"
        >
          Sign in
        </a>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-md space-y-4 p-6">
      <h1 className="text-lg font-semibold">Organization invitation</h1>
      <p className="text-sm text-zinc-400">
        You were invited to join an organization as {session.user.email}. Accepting switches
        your workspace to it — you can switch back to personal any time in settings.
      </p>
      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => void accept()}
          disabled={busy}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "Working…" : "Accept"}
        </button>
        <button
          type="button"
          onClick={() => void decline()}
          disabled={busy}
          className="rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-300 disabled:opacity-50"
        >
          Decline
        </button>
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
    </main>
  );
}
