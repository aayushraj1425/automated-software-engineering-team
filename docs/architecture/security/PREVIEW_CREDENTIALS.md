# Preview credentials and deployment approval

Preview credentials have their own `preview_credentials` table and org-only
FORCE row-level security. They never share the model-provider key loader.
An active organization administrator may PUT or DELETE `/v1/preview-credentials`;
members may GET only `{configured, updated_at}`. The write path uses AES-GCM
encryption and supports credential rotation without returning plaintext.

Kubeconfig input is bounded and must be self-contained. Plugins, auth-provider
hooks, external credential/CA files, production-named contexts, proxy URLs, and
embedded URL credentials are rejected. Validation errors do not echo the input.
The deployment adapter independently checks its execution boundary and uses a
temporary credential file outside the model workspace. Production credentials
should be scoped to preview operations; a human-readable context name is not a
substitute for Kubernetes RBAC.

The initial plan approval authorizes code work. A separate deployment decision
is accepted only while `awaiting_deploy_approval`, from the run owner or an
organization administrator. Approval stores the exact workspace HEAD, actor,
and timestamp. The runtime must compare HEAD to that approval before deployment.
Live approval requires a configured credential. Offline simulations require the
same human decision, but are marked simulated and never claim a live URL.

Expiry cleanup runs in the API maintenance loop and can also be invoked by a
worker. Signed GitHub merged-PR webhooks queue teardown for the matching PR URL.
Cleanup uses a durable, retryable claim; failures keep metadata for retry and
never store adapter exceptions that might contain credentials. Run deletion
requires cleanup to succeed first. Credential deletion is blocked while a live
preview or pending cleanup still needs it. GitLab/Bitbucket merged-PR events are
not currently received by this GitHub-specific webhook; their previews still
expire through the TTL path.

Tests cover encrypted storage, organization isolation, admin checks, input
redaction, exact-commit approval, duplicate approval refusal, simulated expiry,
retryable teardown failure, and signed merged-PR cleanup. A live cluster remains
an external requirement for real Helm/Kubernetes verification.
