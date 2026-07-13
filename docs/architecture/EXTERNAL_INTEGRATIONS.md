# External Integrations

Phase 6 workstream. Plain language; the task list lives in
[BACKLOG.md](../BACKLOG.md).

## The problem

The platform lives on its own island. A run finishes, a plan is written, work
items pile up — but a team's actual day happens somewhere else: in Slack, in a
Jira or Linear board, on a GitLab or Bitbucket repository. Nothing the platform
does today reaches those places, so a person has to go and look.

External integrations connect the platform outward: when something happens here,
tell the tools the team already uses. The first slice is the smallest useful
one — **post a run's outcome to Slack** — built on a foundation the other
integrations will reuse.

```mermaid
flowchart TD
    S[Settings page] -->|save a webhook / token| API["/v1/integrations<br/>(owner-scoped)"]
    API -->|AES-GCM encrypt the config| DB[(integration_connections<br/>ciphertext + a non-secret label)]
    R[Run reaches a terminal state] --> N[notify_run_outcome]
    DB -->|decrypt the owner's connection| N
    N --> AD{Adapter for the kind}
    AD -->|slack| SL[Slack incoming webhook]
    AD -.->|jira / linear / gitlab / bitbucket| LATER[later slices]
    N --> EV[["integration.notified<br/>timeline event"]]
```

## The design

Three pieces, each reused by every future integration:

- **Connections store** — one row per (user, kind) in `integration_connections`.
  A connection's secret config (a Slack webhook URL; later, an API token) is
  encrypted at rest with the same AES-GCM helper as the provider keys
  (`engine/security/crypto.py`, [PROVIDER_KEYS.md](PROVIDER_KEYS.md)). Only the
  ciphertext and a **non-secret label** (e.g. `hooks.slack.com · ending 1a2b`)
  are stored; the secret is decrypted only when a message is about to be sent.
- **Adapter layer** (`engine/integrations/`) — one small module per external
  service. An adapter takes a decrypted config and does exactly one outward
  thing (Slack: post a message to the webhook). Adapters never touch the
  database or a run; they are pure "send this there" functions, easy to test.
- **Dry-run mode** — `INTEGRATIONS_DRY_RUN=1` makes every adapter skip the
  network and report success. Tests and offline dev set it (like `LLM_FAKE` for
  models and `SANDBOX_ENABLED=0` for Docker), so the whole path — configure →
  run finishes → notify → timeline event — runs with no real Slack workspace.

### How a run notifies

When a run reaches a terminal state, the runner already remembers it
(`capture_run_memory`, [KNOWLEDGE_AND_MEMORY.md](KNOWLEDGE_AND_MEMORY.md)).
`notify_run_outcome` runs in the same place, right after capture: it looks up
the run's owner, loads their enabled Slack connection (if any), formats a short
message — did the run succeed, and the pull-request link or the failure reason —
sends it through the adapter, and records an `integration.notified` timeline
event. Like capture, it **never breaks a run**: any failure is logged and
swallowed, and a run with no connection simply notifies nothing (no event).

## API

Owner-scoped, mirroring the provider-keys API:

- `GET /v1/integrations` — which integrations are connected (kind, label,
  enabled, when) — never the secret config.
- `PUT /v1/integrations/{kind}` — set or replace a connection's config;
  validates the kind is *active* and the config's shape (a Slack webhook must be
  a `https://hooks.slack.com/…` URL).
- `DELETE /v1/integrations/{kind}` — disconnect.
- `POST /v1/integrations/{kind}/test` — send a test message now, so the settings
  page can prove a webhook works (returns whether it sent, or was a dry run).

## Kinds

`IntegrationKind` names all the planned services — `slack`, `jira`, `linear`,
`gitlab`, `bitbucket` — so the model and enum are forward-looking, but the API
only accepts the **active** ones. A `PUT` to an inactive kind is refused with
"not yet supported" until its adapter lands. Active so far: `slack`, `linear`,
`jira`.

## Issue-tracker push (Linear, Jira)

The second slice proves the foundation generalizes past notifications: **push a
work item to an issue tracker**. Linear came first (a single GraphQL endpoint,
API-key auth); Jira followed as a differently-shaped second tracker (REST,
HTTP-Basic auth, project keys) behind the same dispatch — the proof the
abstraction holds.

- **Connection** — a Linear connection stores `{api_key, team_id}`; a Jira
  connection stores `{base_url, email, api_token, project_key}`. Both are
  encrypted like the Slack webhook, with a non-secret label (`Linear · team
  …abcdef`, `Jira · ENG @ acme.atlassian.net`).
- **Adapters** — `engine/integrations/linear.py` calls Linear's `issueCreate`
  mutation; `engine/integrations/jira.py` POSTs to `/rest/api/3/issue` (the v3
  description is wrapped as an Atlassian Document Format node). Each returns the
  new issue's URL and human key (`ENG-42`, `PROJ-7`) and, under dry-run, a
  deterministic placeholder so the whole push path runs offline.
- **Dispatch and contract** (`engine/integrations/issues.py`) — owns the shared
  `IssueResult` and maps an issue-tracker kind to its adapter, so the push
  endpoint never names a specific tracker and the next tracker is one more
  branch. (Adapters are imported inside the dispatch function so the dispatcher
  can own `IssueResult` without an import cycle.)
- **The link lives on the work item** — a work item gains `external_issue_url`
  and `external_issue_key`; pushing stores them, and the task board shows the
  item's tracker link. Pushing again re-creates and overwrites (no dedupe yet).
- **Endpoint** — `POST /v1/repositories/{id}/work-items/{item_id}/push` with
  `{kind}` creates the issue from the item's title and description, stores the
  link, and returns the updated work item; `404` when the tracker is not
  connected.

The Slack `test` endpoint stays Slack-only — a tracker's "test" would create a
junk issue, so pushing a real work item is its own proof instead.

## Exit criterion (this slice)

With a Slack webhook saved on the settings page, a run that reaches a terminal
state posts its outcome to Slack and records an `integration.notified` event on
the run timeline. In dry-run mode the same path runs end to end without a real
webhook, which is how it is tested.

## Boundaries

- Outbound only: Slack notifications and Linear/Jira issue push.
  GitLab/Bitbucket merge requests are a separate git-host slice.
- Issue creation only — a fixed issue type (`Task` on Jira) and no field mapping
  beyond title and description. Custom fields, labels, and assignees are later
  refinements.
- Pushing a work item **re-creates** the issue every time — no dedupe against an
  already-pushed item, and no two-way sync (a change in Linear does not flow
  back). Both are later refinements.
- Connections are per **user**, not per organization (same call as the provider
  keys) — organization-shared connections can come with the organization
  switcher.
- No inbound webhooks from these services here (the GitHub PR-review webhook is
  separate, [WEBHOOK_REVIEWER.md](WEBHOOK_REVIEWER.md)).
- No retry queue: a failed notification or push is surfaced, not retried — the
  run's own record and the work item are unaffected.
