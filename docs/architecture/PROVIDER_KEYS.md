# Bring-Your-Own Provider Keys

Design note for *Identity & Keys — bring-your-own provider keys* (a Phase 1
leftover). Plain language; the task list lives in [BACKLOG.md](../BACKLOG.md).

## The problem

Every model call today uses the provider keys in the server's `.env`. That is
fine for one developer, but the platform is multi-user by design: each person
should be able to bring their own Anthropic / OpenAI / Gemini key, spend their
own quota, and remove the key at any time — without their secret ever sitting
readable in the database.

## The design

```mermaid
flowchart LR
    U[Settings page] -->|set / remove a key| A["/v1/provider-keys<br/>(owner-scoped)"]
    A -->|AES-GCM encrypt| DB[(provider_keys table<br/>ciphertext + last 4 digits)]
    C[Chat request or agent run] -->|decrypt the caller's keys| CV[Context variable<br/>provider → key]
    CV --> R[ModelRouter]
    R -->|"user key for the model's provider,<br/>else the server's .env key"| P[LLM provider]
```

- **Storage** — one row per (user, provider) in `provider_keys`. The key is
  encrypted with AES-GCM (`engine/security/crypto.py`); only the ciphertext
  and the last four characters (for the settings page to display) are stored.
  The encryption key comes from `ENGINE_ENCRYPTION_KEY`; when unset (dev), it
  is derived from `ENGINE_SERVICE_SECRET`, so production must set a dedicated
  value.
- **API** — `GET /v1/provider-keys` lists what is configured (provider, last
  four, when) — never the key itself, not even encrypted. `PUT
  /v1/provider-keys/{provider}` sets or replaces; `DELETE` removes. Providers
  are an allow-list: `anthropic`, `openai`, `gemini`.
- **Resolution order** — the router prefers *the caller's key for the model's
  provider*, and falls back to the server's `.env` key when the user has none.
  The user's keys ride a **context variable** set once at the entry points (a
  chat request; a run's planning and execution), so nothing between the
  endpoint and the router needs new parameters — and the router stays the
  single gateway to litellm (ADR-0006).
- **Settings page** — `/settings` shows the three providers, which have a key
  (masked to the last four), and lets the user set or remove one.

## Boundaries

- Keys are per **user**, not per organization — organization-shared keys can
  come now that the organization switcher exists
  (SIGN_IN_AND_ORGANIZATIONS.md); the service JWT already carries the `org`
  claim.
- Repository indexing (embeddings) keeps using the server's key: it runs in a
  background task with no obvious "caller", and embedding cost is small.
  Revisit if hosted multi-tenancy arrives.
- The webhook PR reviewer keeps the server's key for the same reason — GitHub,
  not a user, triggers it.
- No key validation call on save — a wrong key fails at first use with the
  provider's own error, which the run timeline already surfaces.
