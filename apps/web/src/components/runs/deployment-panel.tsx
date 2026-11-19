"use client";

import { FormError } from "../ui/feedback";
import { deploymentStatusLabel, parsePreview } from "./preview";
import { StatusChip } from "./status-chip";
import type { RunDetail } from "./types";

type Props = {
  run: Pick<
    RunDetail,
    | "status"
    | "deployment_status"
    | "preview_deployment"
    | "preview_requested"
    | "preview_options"
    | "deployment_source_sha"
  >;
  busy: boolean;
  error: string | null;
  onDecide: (approved: boolean) => void;
};

/** The preview deploy: its status, the evidence it produced, and the second human
 * approval. A simulated deployment is labelled and never linked, so offline runs
 * can't pass for a live cloud preview. Shows nothing for runs that never asked for
 * a preview. */
export function DeploymentPanel({ run, busy, error, onDecide }: Props) {
  const preview = parsePreview(run.preview_deployment);
  const awaiting = run.status === "awaiting_deploy_approval";
  const requested =
    run.preview_requested === true ||
    awaiting ||
    run.status === "deploying" ||
    (run.deployment_status !== undefined && run.deployment_status !== "not_requested") ||
    preview !== null;
  if (!requested) return null;

  return (
    <section
      className={`space-y-3 rounded-md border p-4 ${
        awaiting ? "border-fuchsia-900 bg-fuchsia-950/30" : "border-zinc-700"
      }`}
      aria-label="Preview deployment"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-medium">Preview deployment</h2>
        <span className="text-xs text-zinc-400">
          {deploymentStatusLabel(run.deployment_status)}
        </span>
      </div>

      {awaiting && (
        <div className="space-y-3">
          <p className="text-sm text-zinc-200">
            The code is built, reviewed and scanned. Nothing is deployed until you approve. The
            deploy goes to a temporary preview environment, never production.
          </p>
          <div className="flex gap-3">
            <button
              onClick={() => onDecide(true)}
              disabled={busy}
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              Approve deploy
            </button>
            <button
              onClick={() => onDecide(false)}
              disabled={busy}
              className="rounded-md border border-red-800 px-4 py-2 text-sm font-medium text-red-300 disabled:opacity-50"
            >
              Reject deploy
            </button>
          </div>
        </div>
      )}
      {(run.preview_options || run.deployment_source_sha) && (
        <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs text-zinc-400">
          {run.deployment_source_sha && (
            <>
              <dt>Checked commit</dt>
              <dd className="break-all font-mono">{run.deployment_source_sha}</dd>
            </>
          )}
          {run.preview_options && (
            <>
              <dt>Chart</dt>
              <dd className="break-all font-mono">
                {run.preview_options.chart_path ?? "deploy/helm"}
              </dd>
              {run.preview_options.values_file && (
                <>
                  <dt>Values</dt>
                  <dd className="break-all font-mono">{run.preview_options.values_file}</dd>
                </>
              )}
              <dt>Image</dt>
              <dd className="break-all font-mono">
                {run.preview_options.image || "From chart values"}
              </dd>
              <dt>Lifetime</dt>
              <dd>{run.preview_options.ttl_hours ?? 24} hours</dd>
              <dt>Smoke paths</dt>
              <dd className="break-all font-mono">
                {(run.preview_options.smoke_paths ?? ["/healthz"]).join(", ")}
              </dd>
            </>
          )}
        </dl>
      )}
      {run.status === "deploying" && (
        <p className="flex items-center gap-2 text-sm text-zinc-300">
          <StatusChip status="deploying" /> Deploying the preview and running smoke tests…
        </p>
      )}

      {preview && (
        <div className="space-y-2 text-sm">
          {preview.status === "simulated" && (
            <p
              role="note"
              className="rounded border border-amber-900 bg-amber-950/40 px-3 py-2 text-xs text-amber-300"
            >
              Simulated, no real cloud deploy happened. Any URL or smoke result below is not
              evidence of a live environment.
            </p>
          )}
          {preview.status === "deployed" && (
            <p className="text-xs text-emerald-300">Live preview environment</p>
          )}
          {preview.status === "deleted" && (
            <p className="text-xs text-zinc-400">Preview removed from the cluster</p>
          )}
          {preview.url && (
            <p className="break-all text-zinc-300">
              <span className="text-zinc-500">URL </span>
              {preview.href ? (
                <a
                  href={preview.href}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sky-300 underline"
                >
                  {preview.url}
                </a>
              ) : (
                <span className="font-mono text-xs">{preview.url}</span>
              )}
            </p>
          )}
          <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs text-zinc-400">
            {preview.namespace && (
              <>
                <dt className="text-zinc-500">Namespace</dt>
                <dd className="font-mono">{preview.namespace}</dd>
              </>
            )}
            {preview.sourceSha && (
              <>
                <dt className="text-zinc-500">Commit</dt>
                <dd className="font-mono">{preview.sourceSha.slice(0, 12)}</dd>
              </>
            )}
            {preview.expiresAt && (
              <>
                <dt className="text-zinc-500">Expires</dt>
                <dd>{new Date(preview.expiresAt).toLocaleString()}</dd>
              </>
            )}
          </dl>
          {preview.error && <FormError message={preview.error} />}
          {preview.smoke && (
            <div className="space-y-1">
              <p className="text-sm text-zinc-300">
                {preview.status === "simulated" ? "Simulated smoke tests" : "Cloud smoke tests"}:{" "}
                <span className={preview.smoke.passed ? "text-emerald-300" : "text-red-300"}>
                  {preview.smoke.passed ? "passed" : "failed"}
                </span>
              </p>
              {preview.smoke.error && <FormError message={preview.smoke.error} />}
              {preview.smoke.checks.length > 0 && (
                <ul className="space-y-0.5 text-xs">
                  {preview.smoke.checks.map((check, index) => (
                    <li key={`${check.path}-${index}`} className="flex gap-2 text-zinc-400">
                      <span
                        className={
                          check.ok === true
                            ? "text-emerald-300"
                            : check.ok === false
                              ? "text-red-300"
                              : "text-zinc-500"
                        }
                      >
                        {check.ok === true ? "pass" : check.ok === false ? "fail" : "n/a"}
                      </span>
                      <span className="font-mono">{check.path}</span>
                      {check.detail && <span className="truncate">{check.detail}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
      <FormError message={error} />
    </section>
  );
}
