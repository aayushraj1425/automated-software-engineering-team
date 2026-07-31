# Security baseline and threat model

**Status:** Living document · **Last updated:** 2026-07-31

This is the high-level threat model: what's worth protecting, where the trust
boundaries are, and how each threat is handled. The controls described here have
all shipped. For the boundary-by-boundary verification against the code, see the
[security audit](security/SECURITY_AUDIT.md); for the containment rules that keep
agents from doing damage, see [ADR-0008](architecture/adr/0008-agent-tool-security-model.md).

## Assets

1. **User source code** (connected repositories, workspaces) — confidentiality and integrity.
2. **Credentials** — LLM provider keys, GitHub tokens, session cookies, the service secret.
3. **Identity data** — users, organizations, sessions (better-auth tables).
4. **Money** — LLM spend; a compromised or runaway agent burns real dollars.
5. **Reputation of generated changes** — malicious or broken PRs opened by the platform.

## Trust boundaries

```
Browser ──(1)── web BFF ──(2)── engine ──(3)── LLM providers
                              └─(4)── agent workspace (untrusted repo content)
                              └─(5)── source host (GitHub / GitLab / Bitbucket)
```

1. **Browser → BFF.** A better-auth session cookie (httpOnly, sameSite=lax); all input validated.
2. **BFF → engine.** A short-lived HS256 service JWT signed with `ENGINE_SERVICE_SECRET`. The engine is unreachable from browsers, and the secret never reaches client bundles. Postgres enforces the same ownership independently via row-level security.
3. **Engine → providers.** Keys live server-side only; requests carry code snippets the user consented to by connecting a repository.
4. **Engine → workspace.** Repository content is **untrusted input** — this is where prompt injection lives. It's contained by a closed tool allowlist, the path jail, no arbitrary shell, a no-egress sandbox, and the human approval gate.
5. **Engine → source host.** Minimal scopes; tokens encrypted at rest.

## Top threats and how they're handled

| Threat | Mitigation |
|---|---|
| Prompt injection in repo files steers agents | Human plan approval and PR gate; closed tool allowlist and path jail; no-egress sandbox for test runs |
| Path traversal / symlink escape from the workspace | The jail resolves symlinks and rejects escapes; dedicated traversal/UNC tests ([`workspace/jail.py`](../apps/engine/src/engine/workspace/jail.py)) |
| Secret exfiltration into prompts or PRs | Tools refuse credential paths; the diff is scanned for secrets before a PR opens; keys never enter prompt context |
| Stolen provider keys | AES-GCM encryption at rest; per-user keys are never logged ([PROVIDER_KEYS](architecture/identity-integrations/PROVIDER_KEYS.md)) |
| Runaway spend | Per-run cost caps; the cheap model tier is the default; a cost metric backs a spend alert |
| Service JWT forgery | 256-bit secret, short expiry, `iat`/`exp` verified; rotated via the environment |
| One user reading another's data | Row-level security on every ownership-carrying table — Postgres refuses it even if a query forgets its `WHERE` ([ROW_LEVEL_SECURITY](architecture/security/ROW_LEVEL_SECURITY.md)) |
| SSRF via user-supplied repository URLs | Git hosts are recognized explicitly; there is no arbitrary-URL fetch tool |
| Dependency supply chain | Lockfiles committed; manifest changes are vulnerability-scanned; pinned Docker base images |

## Controls in place

- **Authentication** — better-auth with database-backed sessions and library-managed password hashing.
- **The engine boundary** — every `/v1/*` route requires the service JWT; `/healthz` is the only public route, and a test sweeps every route to prove it.
- **Least privilege in the database** — user sessions connect as a non-owner role (`asep_api`) under FORCE row-level security, so even raw SQL on a user session can't reach another user's rows or forge the internal service context.
- **Secrets** — only via the environment (`.env` is gitignored; `.env.example` documents every variable). Encryption at rest for provider keys and integration tokens.
- **Agent containment** — closed tool allowlist, path jail, no arbitrary shell, and a Docker sandbox with the network unplugged for test runs.
- **Supply chain and CI** — lint, type, and test on every push; a secrets scan and a dependency scan gate the pull request.
- **Auditability** — an `audit_logs` trail records chat actions and every agent tool call; run timelines are a full, durable record of what each agent did.

## Operator-gated hardening

One boundary hardening needs infrastructure only an operator can provide, tracked
in [OPERATOR_HANDOFF.md](OPERATOR_HANDOFF.md): mutual TLS between the BFF and the
engine, which needs a certificate authority. The network-policy half of that
isolation already ships. Enterprise SSO/SAML is a plausible future addition but
is not yet scoped.

## Reporting a vulnerability

Until a hosted service exists, open a private GitHub security advisory on the
repository.
