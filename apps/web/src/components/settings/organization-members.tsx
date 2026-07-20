"use client";

import { useState } from "react";

import { authClient } from "@/lib/auth-client";

type Member = {
  id: string;
  role: string;
  user: { email: string; name?: string | null };
};

type Invitation = {
  id: string;
  email: string;
  role: string;
  status: string;
};

/** The active organization's members and invitations: invite by email with a
 * role, hand over the accept link (no email provider is wired), change roles,
 * remove members. better-auth enforces its own permission rules server-side —
 * this panel adds UI, not policy (docs/architecture/ORGANIZATION_ROLES.md). */
export function OrganizationMembers({
  members,
  invitations,
  onChanged,
}: {
  members: Member[];
  invitations: Invitation[];
  onChanged: () => void;
}) {
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"member" | "admin">("member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const pending = invitations.filter((invitation) => invitation.status === "pending");

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    const email = inviteEmail.trim();
    if (!email) return;
    setBusy(true);
    setError(null);
    const { error } = await authClient.organization.inviteMember({
      email,
      role: inviteRole,
    });
    setBusy(false);
    if (error) {
      setError(error.message ?? "Could not create the invitation");
      return;
    }
    setInviteEmail("");
    onChanged();
  }

  async function cancelInvitation(invitationId: string) {
    setBusy(true);
    setError(null);
    const { error } = await authClient.organization.cancelInvitation({ invitationId });
    setBusy(false);
    if (error) setError(error.message ?? "Could not cancel the invitation");
    onChanged();
  }

  async function changeRole(memberId: string, role: "member" | "admin") {
    setBusy(true);
    setError(null);
    const { error } = await authClient.organization.updateMemberRole({ memberId, role });
    setBusy(false);
    if (error) setError(error.message ?? "Could not change the role");
    onChanged();
  }

  async function removeMember(memberId: string) {
    setBusy(true);
    setError(null);
    const { error } = await authClient.organization.removeMember({
      memberIdOrEmail: memberId,
    });
    setBusy(false);
    if (error) setError(error.message ?? "Could not remove the member");
    onChanged();
  }

  async function copyLink(invitationId: string) {
    await navigator.clipboard.writeText(
      `${window.location.origin}/accept-invitation/${invitationId}`,
    );
    setCopiedId(invitationId);
    setTimeout(() => setCopiedId(null), 2000);
  }

  return (
    <div className="space-y-3 border-t border-zinc-800 pt-3">
      <h3 className="text-xs font-semibold text-zinc-400">Members</h3>
      {members.map((member) => (
        <div key={member.id} className="flex items-center justify-between gap-3">
          <p className="min-w-0 truncate text-sm text-zinc-200">
            {member.user.name || member.user.email}{" "}
            <span className="text-xs text-zinc-600">{member.user.email}</span>
          </p>
          <div className="flex shrink-0 items-center gap-2">
            {member.role === "owner" ? (
              <span className="text-xs text-zinc-500">owner</span>
            ) : (
              <>
                <select
                  value={member.role}
                  onChange={(e) => void changeRole(member.id, e.target.value as "member" | "admin")}
                  disabled={busy}
                  className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs outline-none focus:border-zinc-500"
                >
                  <option value="member">member</option>
                  <option value="admin">admin</option>
                </select>
                <button
                  type="button"
                  onClick={() => void removeMember(member.id)}
                  disabled={busy}
                  className="text-xs text-zinc-600 hover:text-red-400 disabled:opacity-50"
                >
                  remove
                </button>
              </>
            )}
          </div>
        </div>
      ))}

      {pending.length > 0 && (
        <>
          <h3 className="text-xs font-semibold text-zinc-400">Pending invitations</h3>
          {pending.map((invitation) => (
            <div key={invitation.id} className="flex items-center justify-between gap-3">
              <p className="min-w-0 truncate text-sm text-zinc-400">
                {invitation.email}{" "}
                <span className="text-xs text-zinc-600">as {invitation.role}</span>
              </p>
              <div className="flex shrink-0 items-center gap-3">
                <button
                  type="button"
                  onClick={() => void copyLink(invitation.id)}
                  className="text-xs text-zinc-500 hover:text-zinc-300"
                  title="No invitation emails are sent — share this link yourself"
                >
                  {copiedId === invitation.id ? "copied!" : "copy accept link"}
                </button>
                <button
                  type="button"
                  onClick={() => void cancelInvitation(invitation.id)}
                  disabled={busy}
                  className="text-xs text-zinc-600 hover:text-red-400 disabled:opacity-50"
                >
                  cancel
                </button>
              </div>
            </div>
          ))}
        </>
      )}

      <form onSubmit={(e) => void invite(e)} className="flex gap-2">
        <input
          type="email"
          value={inviteEmail}
          onChange={(e) => setInviteEmail(e.target.value)}
          placeholder="Invite by email"
          className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs outline-none focus:border-zinc-500"
        />
        <select
          value={inviteRole}
          onChange={(e) => setInviteRole(e.target.value as "member" | "admin")}
          className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs outline-none focus:border-zinc-500"
        >
          <option value="member">member</option>
          <option value="admin">admin</option>
        </select>
        <button
          type="submit"
          disabled={busy || !inviteEmail.trim()}
          className="shrink-0 rounded-md bg-zinc-100 px-3 py-1.5 text-xs font-medium text-zinc-900 disabled:opacity-50"
        >
          Invite
        </button>
      </form>
      <p className="text-xs text-zinc-600">
        No invitation emails are sent — copy the accept link and share it yourself.
      </p>
      {error && <p className="text-sm text-red-400">{error}</p>}
    </div>
  );
}
