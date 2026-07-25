import { describe, expect, it } from "vitest";

import { relativeTime } from "./relative-time";

const now = new Date("2026-07-24T12:00:00Z");
const ago = (seconds: number) => new Date(now.getTime() - seconds * 1000).toISOString();

describe("relativeTime", () => {
  it("reports recent moments as 'just now'", () => {
    expect(relativeTime(ago(0), now)).toBe("just now");
    expect(relativeTime(ago(44), now)).toBe("just now");
  });

  it("reports the largest whole unit, singular and plural", () => {
    expect(relativeTime(ago(45), now)).toBe("1 minute ago"); // 45–59s rounds up
    expect(relativeTime(ago(60), now)).toBe("1 minute ago");
    expect(relativeTime(ago(300), now)).toBe("5 minutes ago");
    expect(relativeTime(ago(3600), now)).toBe("1 hour ago");
    expect(relativeTime(ago(3 * 3600), now)).toBe("3 hours ago");
    expect(relativeTime(ago(86400), now)).toBe("1 day ago");
    expect(relativeTime(ago(2 * 86400), now)).toBe("2 days ago");
    expect(relativeTime(ago(2 * 604800), now)).toBe("2 weeks ago");
    expect(relativeTime(ago(400 * 86400), now)).toBe("1 year ago");
  });

  it("does not roll an age up to the next unit early", () => {
    // ~11.5 months must stay in months, not jump to "1 year ago".
    expect(relativeTime(ago(Math.round(11.5 * 2629800)), now)).toBe("11 months ago");
    // Just over a year is the first "1 year ago".
    expect(relativeTime(ago(13 * 2629800), now)).toBe("1 year ago");
  });

  it("is empty for a null or unparseable timestamp", () => {
    expect(relativeTime(null, now)).toBe("");
    expect(relativeTime(undefined, now)).toBe("");
    expect(relativeTime("not-a-date", now)).toBe("");
  });

  it("treats a future timestamp (clock skew) as now", () => {
    expect(relativeTime(ago(-500), now)).toBe("just now");
  });
});
