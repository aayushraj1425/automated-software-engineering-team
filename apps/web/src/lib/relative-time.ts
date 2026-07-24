/** A coarse, human "… ago" phrasing of an ISO timestamp — `just now`,
 * `5 minutes ago`, `3 hours ago`, `2 days ago`, and so on. Pure: pass `now`
 * to make it testable without mocking the clock. Returns "" for a null or
 * unparseable timestamp. Design note: docs/architecture/REPOSITORY_INDEX_FRESHNESS.md. */
export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";

  const seconds = Math.round((now.getTime() - then) / 1000);
  if (seconds < 0) return "just now"; // a clock skew into the future reads as now
  if (seconds < 45) return "just now";

  // Under 45s already read as "just now"; from there, round to the coarsest
  // unit whose count stays below the next unit's threshold.
  const units: [limit: number, secondsPer: number, name: string][] = [
    [60, 60, "minute"],
    [24, 3600, "hour"],
    [7, 86400, "day"],
    [4.35, 604800, "week"],
    [12, 2629800, "month"],
    [Infinity, 31557600, "year"],
  ];
  for (const [limit, secondsPer, name] of units) {
    const value = Math.round(seconds / secondsPer);
    if (value < limit) {
      return `${value} ${name}${value === 1 ? "" : "s"} ago`;
    }
  }
  return "just now"; // unreachable; the year bucket has no upper limit
}
