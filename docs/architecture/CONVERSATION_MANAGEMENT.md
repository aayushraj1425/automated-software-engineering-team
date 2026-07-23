# Conversation Management — rename and delete

**Status:** Design accepted · **Phase:** 8 follow-up · **Written:** 2026-07-23

## The problem

Chat conversations were create-and-read only: they accumulated in the sidebar,
auto-titled from the first message, with no way to tidy them — rename a
mislabelled thread, delete a throwaway. A cleanup gap, and the direct parallel
to deleting a run.

## The design

Two endpoints on the existing conversations API, both owner-scoped through one
helper (`_owned_conversation`), because a conversation is **personal** — never
shared with an organization ([ORGANIZATION_SHARING.md](ORGANIZATION_SHARING.md)):

- `PATCH /v1/conversations/{id}` `{ "title": "…" }` — rename. The title is
  validated non-blank and trimmed (a pydantic `field_validator`), so a
  whitespace-only title is a **422**, not a silently-empty label.
- `DELETE /v1/conversations/{id}` — delete the conversation and its messages
  (the `messages` FK is `ON DELETE CASCADE`), returning **204**.

Missing and not-yours both return **404** — no existence leak, the same rule the
message-list read already used (now sharing the helper). The chat sidebar shows
rename (✎) and delete (✕) affordances on hover; deleting the open conversation
resets the panel to a new chat.

## Boundaries

- **No soft delete / undo.** A deleted conversation is gone with its messages;
  this matches the run-delete behaviour and keeps the model simple.
- **Rename is manual only.** The automatic first-message titling is unchanged;
  this just lets a human override it.
