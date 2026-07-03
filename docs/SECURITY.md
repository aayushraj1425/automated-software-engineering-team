# Security Baseline & Threat Model

**Status:** Living document · **Last updated:** 2026-07-02
Deep-dive on agent containment: [ADR-0008](architecture/adr/0008-agent-tool-security-model.md).

## Assets

1. **User source code** (connected repos, workspaces) — confidentiality + integrity.
2. **Credentials** — LLM provider keys, GitHub tokens, session cookies, service secret.
3. **Identity data** — users, orgs, sessions (better-auth tables).
4. **Money** — LLM spend (a compromised or runaway agent burns real dollars).
5. **Reputation of generated changes** — malicious/broken PRs signed by the platform.

## Trust boundaries

```
Browser ──(1)── web BFF ──(2)── engine ──(3)── LLM providers
                              └─(4)── agent workspace (untrusted repo content)
                              └─(5)── GitHub API
```

1. Session cookie (better-auth, httpOnly, sameSite=lax); all input validated.
2. Short-lived HS256 service JWT (`ENGINE_SERVICE_SECRET`); engine unreachable from
   browsers; secret never in client bundles.
3. Keys server-side only; requests carry code snippets — users consent by connecting a repo.
4. **Repo content is untrusted input** (prompt injection lives here). Mitigations:
   closed tool allowlist, path jail, no shell (Phase 1), no-egress sandbox (Phase 3), human PR gate.
5. Minimal GitHub scopes; tokens encrypted at rest (Phase 1).

## Top threats & mitigations

| Threat | Mitigation (phase) |
|---|---|
| Prompt injection in repo files steers agents | Human plan approval + PR gate (Phase 1); tool allowlist + path jail (Phase 1); no-egress sandbox (Phase 3); injection eval suite (Phase 3) |
| Path traversal / symlink escape from workspace | Jail resolves symlinks, rejects escapes; dedicated traversal/UNC tests (Phase 1) |
| Secret exfiltration into prompts/PRs | Tools refuse `.env*`/credential paths (Phase 1); secrets scanner on diffs (Phase 3); keys never enter prompt context |
| Stolen provider keys | AES-GCM at rest, master key from env (Phase 1); per-user keys never logged |
| Runaway spend | Per-run token/cost caps (Phase 1); tier defaults favor cheap models |
| Service JWT forgery | 256-bit secret, 60s expiry, `iat/exp` verified; rotate via env |
| SSRF via user-supplied repo URLs | Allowlist git hosts; no arbitrary URL fetch tools until sanitized fetcher ships |
| Dependency supply chain | Lockfiles committed; Dependabot/audit in CI (Phase 3); pinned Docker base images |

## Current controls (Phase 0)

- Auth: better-auth, DB sessions, password hashing handled by the library.
- Engine `/v1/*` requires the service JWT; `/healthz` is the only public route.
- Secrets only via env (`.env` gitignored; `.env.example` documents every variable).
- `LLM_FAKE` mode keeps CI free of real credentials.
- Audit skeleton: `audit_logs` table written from the first chat endpoint onward.
- CI runs lint/type/test on every PR; no direct pushes to `main` once the repo is on GitHub.

## Security work by phase

- **Phase 1:** path jail + tests, encrypted BYO keys, budget caps, tool audit trail, rate limiting.
- **Phase 3:** sandbox (no egress), secrets detection, dependency scanning, injection evals.
- **Phase 7:** row-level security, mTLS/service mesh option, SSO/SAML, pen test, backup/DR drills.

## Reporting

Until a hosted service exists: open a private GitHub security advisory on the repo.
