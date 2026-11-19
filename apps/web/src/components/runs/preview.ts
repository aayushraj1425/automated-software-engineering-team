export type SmokeCheck = {
  path: string;
  ok: boolean | null;
  detail: string;
};

export type PreviewInfo = {
  status: "deployed" | "simulated" | "failed" | "deleted" | "unknown";
  /** True only for a real, live deployment. Everything else must not look live. */
  live: boolean;
  /** The preview URL as text; null when absent. */
  url: string | null;
  /** The URL as a link target: only for a live http(s) deployment. */
  href: string | null;
  namespace: string | null;
  expiresAt: string | null;
  sourceSha: string | null;
  error: string | null;
  smoke: { passed: boolean; error: string | null; checks: SmokeCheck[] } | null;
};

const STATUSES = new Set(["deployed", "simulated", "failed", "deleted"]);
const MAX_TEXT = 300;
const MAX_CHECKS = 20;

function text(value: unknown, max = MAX_TEXT): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.length > max ? `${trimmed.slice(0, max)}…` : trimmed;
}

function isHttpUrl(value: string): boolean {
  try {
    const protocol = new URL(value).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

function toCheck(raw: unknown): SmokeCheck {
  const check = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const detail =
    text(check.detail) ??
    text(check.error) ??
    (typeof check.status_code === "number" ? `HTTP ${check.status_code}` : null) ??
    "";
  const ok =
    typeof check.ok === "boolean"
      ? check.ok
      : typeof check.passed === "boolean"
        ? check.passed
        : null;
  return { path: text(check.path) ?? text(check.url) ?? "(unnamed check)", ok, detail };
}

/** Read the run's untyped `preview_deployment` object as evidence the screen can
 * show. The payload is treated as untrusted: unknown fields are ignored, text is
 * bounded, and a URL only becomes a link for a real, live http(s) deployment. A
 * simulated deployment (offline or fake mode) never looks live, even when it
 * carries a URL string. Returns null when there is nothing to show. */
export function parsePreview(raw: Record<string, unknown> | null | undefined): PreviewInfo | null {
  if (!raw || typeof raw !== "object" || Object.keys(raw).length === 0) return null;
  const status = typeof raw.status === "string" && STATUSES.has(raw.status) ? raw.status : null;
  const url = text(raw.url, 500);
  const live = status === "deployed";
  const smokeRaw = raw.smoke && typeof raw.smoke === "object" ? (raw.smoke as object) : null;
  const smoke = smokeRaw
    ? (() => {
        const s = smokeRaw as Record<string, unknown>;
        return {
          passed: s.passed === true,
          error: text(s.error),
          checks: (Array.isArray(s.checks) ? s.checks : []).slice(0, MAX_CHECKS).map(toCheck),
        };
      })()
    : null;
  return {
    status: (status ?? "unknown") as PreviewInfo["status"],
    live,
    url,
    href: live && url && isHttpUrl(url) ? url : null,
    namespace: text(raw.namespace, 100),
    expiresAt: text(raw.expires_at, 60),
    sourceSha: text(raw.source_sha, 40),
    error: text(raw.error),
    smoke,
  };
}

/** Plain-English label for the run's `deployment_status`. */
export function deploymentStatusLabel(status: string | undefined): string {
  switch (status) {
    case "approved":
      return "Approved";
    case "rejected":
      return "Rejected";
    case "deployed":
      return "Deployed";
    case "deploying":
      return "Deploying";
    case "failed":
      return "Failed";
    case "not_requested":
    case undefined:
    case "":
      return "Not requested";
    default:
      return status.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  }
}
