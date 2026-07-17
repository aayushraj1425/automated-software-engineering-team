"use client";

import { useCallback, useEffect, useState } from "react";

type Connection = {
  kind: string;
  label: string;
  enabled: boolean;
  updated_at: string;
};

type TestResult = { ok: boolean; dry_run: boolean; detail: string };

const inputClasses =
  "w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500";

/** Outbound integrations, each encrypted at rest and never returned — only a
 * non-secret label comes back. Slack posts run outcomes; Linear turns a work
 * item into an issue from the planning board. */
export function IntegrationsPanel() {
  const [connections, setConnections] = useState<Record<string, Connection>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  // Slack draft
  const [webhook, setWebhook] = useState("");
  // Linear draft
  const [apiKey, setApiKey] = useState("");
  const [teamId, setTeamId] = useState("");
  // Jira draft
  const [jiraUrl, setJiraUrl] = useState("");
  const [jiraEmail, setJiraEmail] = useState("");
  const [jiraToken, setJiraToken] = useState("");
  const [jiraProject, setJiraProject] = useState("");
  // GitLab draft
  const [gitlabToken, setGitlabToken] = useState("");
  const [gitlabUrl, setGitlabUrl] = useState("");
  const [bitbucketUsername, setBitbucketUsername] = useState("");
  const [bitbucketPassword, setBitbucketPassword] = useState("");

  const refresh = useCallback(async () => {
    const res = await fetch("/api/integrations");
    if (!res.ok) return;
    const rows: Connection[] = await res.json();
    setConnections(Object.fromEntries(rows.map((r) => [r.kind, r])));
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function save(kind: string, config: Record<string, string>) {
    setBusy(kind);
    setError(null);
    setStatus(null);
    try {
      const res = await fetch(`/api/integrations/${kind}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ config }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail ?? `Could not save (${res.status})`);
      }
      setWebhook("");
      setApiKey("");
      setTeamId("");
      setJiraUrl("");
      setJiraEmail("");
      setJiraToken("");
      setJiraProject("");
      setGitlabToken("");
      setGitlabUrl("");
      setBitbucketUsername("");
      setBitbucketPassword("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  async function remove(kind: string) {
    setBusy(kind);
    setError(null);
    setStatus(null);
    try {
      const res = await fetch(`/api/integrations/${kind}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) throw new Error(`Could not disconnect (${res.status})`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  async function sendTest(kind: string) {
    setBusy(kind);
    setError(null);
    setStatus(null);
    try {
      const res = await fetch(`/api/integrations/${kind}/test`, { method: "POST" });
      const result: TestResult = await res.json();
      if (!res.ok) throw new Error(`Test failed (${res.status})`);
      setStatus(result.detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  const slack = connections.slack;
  const linear = connections.linear;
  const jira = connections.jira;
  const gitlab = connections.gitlab;
  const bitbucket = connections.bitbucket;

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6 pt-0">
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Integrations</h2>
        <p className="text-xs text-zinc-500">
          Connect an outbound service and the platform reaches it from your work. Secrets are
          encrypted at rest and never shown again.
        </p>
      </section>

      {/* Slack */}
      <section className="space-y-2 rounded-md border border-zinc-800 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-200">Slack</p>
          {slack ? (
            <span className="text-xs text-emerald-400">
              {slack.label} · {new Date(slack.updated_at).toLocaleDateString()}
            </span>
          ) : (
            <span className="text-xs text-zinc-600">not connected</span>
          )}
        </div>
        <p className="text-xs text-zinc-500">
          Paste a Slack{" "}
          <a
            href="https://api.slack.com/messaging/webhooks"
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2 hover:text-zinc-300"
          >
            incoming-webhook URL
          </a>
          . Run outcomes are posted to that channel.
        </p>
        <div className="flex gap-3">
          <input
            type="password"
            value={webhook}
            onChange={(e) => setWebhook(e.target.value)}
            placeholder={slack ? "Replace the webhook (https://hooks.slack.com/…)" : "https://hooks.slack.com/…"}
            autoComplete="off"
            className={inputClasses}
          />
          <button
            type="button"
            onClick={() => void save("slack", { webhook_url: webhook.trim() })}
            disabled={busy === "slack" || !webhook.trim()}
            className="shrink-0 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
          >
            {busy === "slack" ? "Saving…" : slack ? "Replace" : "Save"}
          </button>
          {slack && (
            <>
              <button
                type="button"
                onClick={() => void sendTest("slack")}
                disabled={busy === "slack"}
                className="shrink-0 rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-300 disabled:opacity-50"
              >
                Send test
              </button>
              <button
                type="button"
                onClick={() => void remove("slack")}
                disabled={busy === "slack"}
                className="shrink-0 rounded-md border border-red-800 px-4 py-2 text-sm text-red-300 disabled:opacity-50"
              >
                Remove
              </button>
            </>
          )}
        </div>
      </section>

      {/* Linear */}
      <section className="space-y-2 rounded-md border border-zinc-800 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-200">Linear</p>
          {linear ? (
            <span className="text-xs text-emerald-400">
              {linear.label} · {new Date(linear.updated_at).toLocaleDateString()}
            </span>
          ) : (
            <span className="text-xs text-zinc-600">not connected</span>
          )}
        </div>
        <p className="text-xs text-zinc-500">
          Paste a Linear{" "}
          <a
            href="https://linear.app/settings/api"
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2 hover:text-zinc-300"
          >
            personal API key
          </a>{" "}
          and the team id to create issues in. Push a work item to Linear from the planning board.
        </p>
        <div className="flex flex-wrap gap-3">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={linear ? "Replace the API key (lin_api_…)" : "API key (lin_api_…)"}
            autoComplete="off"
            className={inputClasses}
          />
          <div className="flex w-full gap-3">
            <input
              value={teamId}
              onChange={(e) => setTeamId(e.target.value)}
              placeholder="Team id"
              className={inputClasses}
            />
            <button
              type="button"
              onClick={() => void save("linear", { api_key: apiKey.trim(), team_id: teamId.trim() })}
              disabled={busy === "linear" || !apiKey.trim() || !teamId.trim()}
              className="shrink-0 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
            >
              {busy === "linear" ? "Saving…" : linear ? "Replace" : "Save"}
            </button>
            {linear && (
              <button
                type="button"
                onClick={() => void remove("linear")}
                disabled={busy === "linear"}
                className="shrink-0 rounded-md border border-red-800 px-4 py-2 text-sm text-red-300 disabled:opacity-50"
              >
                Remove
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Jira */}
      <section className="space-y-2 rounded-md border border-zinc-800 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-200">Jira</p>
          {jira ? (
            <span className="text-xs text-emerald-400">
              {jira.label} · {new Date(jira.updated_at).toLocaleDateString()}
            </span>
          ) : (
            <span className="text-xs text-zinc-600">not connected</span>
          )}
        </div>
        <p className="text-xs text-zinc-500">
          Connect Jira Cloud with your site URL, an{" "}
          <a
            href="https://id.atlassian.com/manage-profile/security/api-tokens"
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2 hover:text-zinc-300"
          >
            API token
          </a>{" "}
          and email, and the project key to create issues in.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <input
            value={jiraUrl}
            onChange={(e) => setJiraUrl(e.target.value)}
            placeholder="https://your-site.atlassian.net"
            className={inputClasses}
          />
          <input
            value={jiraProject}
            onChange={(e) => setJiraProject(e.target.value)}
            placeholder="Project key (e.g. ENG)"
            className={inputClasses}
          />
          <input
            value={jiraEmail}
            onChange={(e) => setJiraEmail(e.target.value)}
            placeholder="Email"
            autoComplete="off"
            className={inputClasses}
          />
          <input
            type="password"
            value={jiraToken}
            onChange={(e) => setJiraToken(e.target.value)}
            placeholder={jira ? "Replace the API token" : "API token"}
            autoComplete="off"
            className={inputClasses}
          />
        </div>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() =>
              void save("jira", {
                base_url: jiraUrl.trim(),
                email: jiraEmail.trim(),
                api_token: jiraToken.trim(),
                project_key: jiraProject.trim(),
              })
            }
            disabled={
              busy === "jira" ||
              !jiraUrl.trim() ||
              !jiraEmail.trim() ||
              !jiraToken.trim() ||
              !jiraProject.trim()
            }
            className="shrink-0 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
          >
            {busy === "jira" ? "Saving…" : jira ? "Replace" : "Save"}
          </button>
          {jira && (
            <button
              type="button"
              onClick={() => void remove("jira")}
              disabled={busy === "jira"}
              className="shrink-0 rounded-md border border-red-800 px-4 py-2 text-sm text-red-300 disabled:opacity-50"
            >
              Remove
            </button>
          )}
        </div>
      </section>

      {/* GitLab */}
      <section className="space-y-2 rounded-md border border-zinc-800 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-200">GitLab</p>
          {gitlab ? (
            <span className="text-xs text-emerald-400">
              {gitlab.label} · {new Date(gitlab.updated_at).toLocaleDateString()}
            </span>
          ) : (
            <span className="text-xs text-zinc-600">not connected</span>
          )}
        </div>
        <p className="text-xs text-zinc-500">
          Connect a GitLab{" "}
          <a
            href="https://gitlab.com/-/user_settings/personal_access_tokens"
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2 hover:text-zinc-300"
          >
            personal access token
          </a>{" "}
          (scope <code className="text-zinc-400">api</code>) and a run on a GitLab repository
          opens a merge request when it finishes.
        </p>
        <div className="flex gap-3">
          <input
            type="password"
            value={gitlabToken}
            onChange={(e) => setGitlabToken(e.target.value)}
            placeholder={gitlab ? "Replace the token (glpat-…)" : "Personal access token (glpat-…)"}
            autoComplete="off"
            className={inputClasses}
          />
          <input
            value={gitlabUrl}
            onChange={(e) => setGitlabUrl(e.target.value)}
            placeholder="Base URL (optional, defaults to https://gitlab.com)"
            className={inputClasses}
          />
          <button
            type="button"
            onClick={() =>
              void save("gitlab", {
                token: gitlabToken.trim(),
                ...(gitlabUrl.trim() ? { base_url: gitlabUrl.trim() } : {}),
              })
            }
            disabled={busy === "gitlab" || !gitlabToken.trim()}
            className="shrink-0 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
          >
            {busy === "gitlab" ? "Saving…" : gitlab ? "Replace" : "Save"}
          </button>
          {gitlab && (
            <button
              type="button"
              onClick={() => void remove("gitlab")}
              disabled={busy === "gitlab"}
              className="shrink-0 rounded-md border border-red-800 px-4 py-2 text-sm text-red-300 disabled:opacity-50"
            >
              Remove
            </button>
          )}
        </div>
      </section>

      {/* Bitbucket */}
      <section className="space-y-2 rounded-md border border-zinc-800 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-200">Bitbucket</p>
          {bitbucket ? (
            <span className="text-xs text-emerald-400">
              {bitbucket.label} · {new Date(bitbucket.updated_at).toLocaleDateString()}
            </span>
          ) : (
            <span className="text-xs text-zinc-600">not connected</span>
          )}
        </div>
        <p className="text-xs text-zinc-500">
          Connect your Bitbucket username and an{" "}
          <a
            href="https://bitbucket.org/account/settings/app-passwords/"
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2 hover:text-zinc-300"
          >
            app password
          </a>{" "}
          (repositories: write, pull requests: write) and a run on a Bitbucket repository
          opens a pull request when it finishes.
        </p>
        <div className="flex gap-3">
          <input
            value={bitbucketUsername}
            onChange={(e) => setBitbucketUsername(e.target.value)}
            placeholder="Username"
            autoComplete="off"
            className={inputClasses}
          />
          <input
            type="password"
            value={bitbucketPassword}
            onChange={(e) => setBitbucketPassword(e.target.value)}
            placeholder={bitbucket ? "Replace the app password" : "App password"}
            autoComplete="off"
            className={inputClasses}
          />
          <button
            type="button"
            onClick={() =>
              void save("bitbucket", {
                username: bitbucketUsername.trim(),
                app_password: bitbucketPassword.trim(),
              })
            }
            disabled={
              busy === "bitbucket" || !bitbucketUsername.trim() || !bitbucketPassword.trim()
            }
            className="shrink-0 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
          >
            {busy === "bitbucket" ? "Saving…" : bitbucket ? "Replace" : "Save"}
          </button>
          {bitbucket && (
            <button
              type="button"
              onClick={() => void remove("bitbucket")}
              disabled={busy === "bitbucket"}
              className="shrink-0 rounded-md border border-red-800 px-4 py-2 text-sm text-red-300 disabled:opacity-50"
            >
              Remove
            </button>
          )}
        </div>
      </section>

      {status && <p className="text-sm text-emerald-400">{status}</p>}
      {error && <p className="text-sm text-red-400">{error}</p>}
    </div>
  );
}
