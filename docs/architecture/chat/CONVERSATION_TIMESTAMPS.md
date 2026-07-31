# When a conversation was last active

**Status:** Implemented · **Design note**

## What this is about

The chat sidebar shows each conversation's title and nothing else, so a chat
from an hour ago looks identical to one from last month. The runs list already
shows a coarse "… ago" next to each run ([RUN_TIMESTAMPS.md](../runs-ui/RUN_TIMESTAMPS.md));
this brings the same cue to the chat sidebar, so the list reads as a timeline.

## The rule

Under each conversation's title, show `relativeTime(updated_at)` — the last time
the conversation changed (a new message, or a rename). `updated_at` is the
meaningful "last active" moment, the same field the list is already ordered by,
so the newest conversations naturally read "just now" at the top.

Nothing new goes over the wire: `ConversationOut` has always carried
`updated_at`, and the web `ConversationSummary` type already has it. This is the
**third caller** of the shared, pure `relativeTime` helper (after the repository
card and the runs list) — exactly the reuse that put it in `lib`
([REPOSITORY_INDEX_FRESHNESS.md](../repository-intelligence/REPOSITORY_INDEX_FRESHNESS.md)).

## Boundaries

- **Purely presentational.** No API, type, schema, or engine change — the value
  was already on the wire.
- **No live ticking.** The phrasing is computed on render (and on the next
  sidebar refresh, which already happens after send/rename/delete); it does not
  update on a timer. A conversation that says "2 minutes ago" is as fresh as the
  last render, which is the same contract the runs list uses.
