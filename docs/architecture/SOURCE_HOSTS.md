# Source Hosts

Phase 6 workstream (part of External Integrations). Plain language; the task
list lives in [BACKLOG.md](../BACKLOG.md).

## The problem

A finished run pushes its branch and opens a **pull request** — but only on
GitHub. Teams whose code lives on GitLab (or Bitbucket) get the branch push at
best and no merge request at all. The publish step hard-codes one host.

Source hosts make the publish step **host-aware**: detect where the repository
lives and open the right kind of request there — a GitHub pull request, a GitLab
merge request — using the credentials for that host. GitLab is the first new
host; Bitbucket reuses everything behind it.

```mermaid
flowchart TD
    R[Run passes review, sandbox, scans] --> P[publish]
    P --> D{Which host is<br/>the repo on?}
    D -->|github.com| GH[push with the env token<br/>open a pull request]
    D -->|gitlab.com| GL[push with the owner's token<br/>open a merge request]
    D -->|bitbucket.org| BB[push with the owner's<br/>app password<br/>open a pull request]
    D -->|local / unknown| PUSHONLY[push only, no request]
    GL --> C[(owner's connection,<br/>encrypted at rest)]
    BB --> C
    GH --> EV[["branch.published<br/>timeline event"]]
    GL --> EV
    BB --> EV
```

## The design

The change is **strictly additive** — the GitHub path is untouched, so the
golden run is unchanged. `_publish` gains host detection and a GitLab branch
beside the existing GitHub one.

- **Host detection** — `parse_github_repo` already recognizes GitHub URLs;
  `parse_gitlab_repo` (in `engine/integrations/gitlab.py`) recognizes
  `gitlab.com` URLs and returns the project path (which can be nested,
  `group/subgroup/repo`). A URL that matches neither (a local path, an unknown
  host) publishes the branch only, exactly as before.
- **Credentials from the connection store** — GitHub keeps using the server's
  `GITHUB_TOKEN` (unchanged). GitLab uses the run owner's **encrypted GitLab
  connection** — the same per-user store as Slack/Linear/Jira
  ([EXTERNAL_INTEGRATIONS.md](EXTERNAL_INTEGRATIONS.md)): a `{token, base_url}`
  config, `base_url` defaulting to `https://gitlab.com`. GitLab is a connection
  kind but **not** an issue tracker, so it is never a work-item push target.
- **Push auth** — `push_branch` gained an optional credential. With none (the
  default) it keeps its GitHub-env behavior byte-for-byte; `_publish` passes an
  `("oauth2", token)` credential for a GitLab repo so the branch push
  authenticates. The token is redacted from any error the same way the GitHub
  token already is.
- **Merge request** — `open_merge_request` POSTs to
  `{base_url}/api/v4/projects/{url-encoded path}/merge_requests` with a
  `PRIVATE-TOKEN` header and returns the MR's `web_url`. Dry-run
  (`INTEGRATIONS_DRY_RUN=1`) returns a deterministic placeholder so the piece is
  testable offline.

## Bitbucket, behind the same seam *(added 2026-07-17)*

Bitbucket is the third host, and it reuses every joint GitLab cut:

- **Detection** — `parse_bitbucket_repo` (in
  `engine/integrations/bitbucket.py`) recognizes `bitbucket.org` URLs and
  returns `workspace/repo` (Bitbucket paths never nest).
- **Credentials** — a Bitbucket **connection** in the same encrypted per-user
  store: `{username, app_password}` (Bitbucket Cloud's app passwords; the
  label shows the username, never the password).
- **Push auth** — the same `push_branch` credential seam:
  `(username, app_password)` authenticates the https push, redacted from any
  error like the other tokens.
- **Pull request** — `open_pull_request` POSTs to
  `https://api.bitbucket.org/2.0/repositories/{workspace}/{repo}/pullrequests`
  with HTTP Basic auth and returns the PR's html link. Dry-run returns a
  deterministic placeholder, so the piece is testable offline.
- The manual **Push branch** button on the run page (WORKSPACE_PANELS.md)
  resolves the same credential, so a Bitbucket run's hand-made commit also
  reaches its host.

## Exit criterion

A run on a `gitlab.com` repository, with the owner's GitLab token connected,
pushes its branch to GitLab and opens a merge request, its URL recorded on the
run exactly like a GitHub pull request — and the same for a `bitbucket.org`
repository with the owner's app password connected. GitHub runs are unchanged.

## Self-hosted GitLab *(added 2026-07-18)*

The GitLab connection's `base_url` now does double duty: besides naming the
API endpoint, it names the instance for **detection**. A repository URL on
no SaaS host — `https://git.acme.dev/team/demo`, or its ssh form — is
matched against the host in the user's connection (`connection_repo_path`);
on a match, the push authenticates with the connection's token and the
merge request goes to the connection's API. GitHub URLs never consult the
connection, and a suffix-spoofing host (`git.acme.dev.evil.io`) does not
match.

## Boundaries

- **Self-hosted Bitbucket stays out.** Bitbucket Server/Data Center speaks
  a different API (1.0-style REST, different auth) — a different protocol,
  not just a different host. It gets its own slice if a user ever needs it.
- No two-way sync and no draft/reviewer/label options on the merge/pull
  request — title, description, source and target branch only.
- Host credentials are per **user**, not per organization (same call as the
  other connections).
