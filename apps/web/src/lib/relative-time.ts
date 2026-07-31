/** A coarse, human "… ago" phrasing of an ISO timestamp — `just now`,
 * `5 minutes ago`, `3 hours ago`, `2 days ago`, and so on. Pure: pass `now`
 * to make it testable without mocking the clock. Returns "" for a null or
 * unparseable timestamp. Design note: docs/architecture/repository-intelligence/REPOSITORY_INDEX_FRESHNESS.md. */
export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";

  const seconds = Math.round((now.getTime() - then) / 1000);
  // Under 45s — including a clock skew into the future (negative) — reads as now.
  if (seconds < 45) return "just now";

  // Report the largest *whole* unit that fits: floor, largest first. Flooring
  // (not rounding against the next threshold) means an age never rolls up early
  // — e.g. 11½ months stays "11 months ago" instead of jumping to "1 year ago".
  const units: [secondsPer: number, name: string][] = [
    [31557600, "year"],
    [2629800, "month"],
    [604800, "week"],
    [86400, "day"],
    [3600, "hour"],
    [60, "minute"],
  ];
  for (const [secondsPer, name] of units) {
    const value = Math.floor(seconds / secondsPer);
    if (value >= 1) {
      return `${value} ${name}${value === 1 ? "" : "s"} ago`;
    }
  }
  return "1 minute ago"; // 45–59s rounds up to the smallest named unit
}
