// downloadTextFile drives a hidden <a download>. The fiddly parts are lifecycle:
// the anchor must be in the document when clicked (some browsers need it) and
// the object URL must be revoked *after* the click, not synchronously, or the
// download can be aborted before the blob is read.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { downloadMarkdownFrom, downloadTextFile } from "./download";

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("URL", {
    createObjectURL: vi.fn(() => "blob:fake"),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("downloadTextFile", () => {
  it("clicks an in-document anchor with the filename, then cleans it up", () => {
    const clicked: HTMLAnchorElement[] = [];
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      // Assert the anchor is attached at click time, before it's removed.
      expect(document.body.contains(this)).toBe(true);
      clicked.push(this);
    });

    downloadTextFile("report.md", "# hi");

    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("report.md");
    expect(clicked[0].getAttribute("href")).toBe("blob:fake");
    // Removed again after the click.
    expect(document.body.contains(clicked[0])).toBe(false);
    clickSpy.mockRestore();
  });

  it("revokes the object URL only after the click returns", () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    downloadTextFile("report.md", "# hi");

    // Not revoked synchronously — that can abort the download mid-read.
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:fake");
  });
});

// downloadMarkdownFrom is called fire-and-forget (`void downloadMarkdownFrom(...)`),
// so its whole contract is to be a no-op on any failure: never reject, never save a
// file named "undefined". These tests pin each failure mode alongside the happy path.
describe("downloadMarkdownFrom", () => {
  it("saves the returned markdown under the returned filename", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ markdown: "# report", filename: "run-42.md" }),
      })),
    );

    await downloadMarkdownFrom("/api/runs/42/report");

    const anchor = click.mock.instances[0] as unknown as HTMLAnchorElement;
    expect(click).toHaveBeenCalledTimes(1);
    expect(anchor.download).toBe("run-42.md");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("does nothing when the response is not ok", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, json: async () => ({ markdown: "x", filename: "y.md" }) })),
    );

    await downloadMarkdownFrom("/api/runs/42/report");

    expect(click).not.toHaveBeenCalled();
  });

  it("does nothing when the body is missing the expected fields", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ markdown: 123, filename: null }) })),
    );

    await downloadMarkdownFrom("/api/runs/42/report");

    expect(click).not.toHaveBeenCalled();
  });

  it("swallows a network error instead of rejecting", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    await expect(downloadMarkdownFrom("/api/runs/42/report")).resolves.toBeUndefined();
    expect(click).not.toHaveBeenCalled();
  });
});
