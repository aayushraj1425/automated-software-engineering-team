// The copy button flips to "Copied" for a moment and announces the copy to
// screen readers. The timer is the fiddly part: a rapid second click must
// restart the window (not let an earlier timer flip it back early), and an
// unmount mid-window must not leave a timer setting state on a gone component.

import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CopyButton } from "@/components/ui/copy-button";

const writeText = vi.fn<(text: string) => Promise<void>>();

beforeEach(() => {
  vi.useFakeTimers();
  writeText.mockReset().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function click(button: HTMLElement) {
  // The onClick is async (awaits writeText); flush its microtasks under fake timers.
  await act(async () => {
    button.click();
  });
}

describe("CopyButton", () => {
  it("copies the text and flips to Copied, then back after the delay", async () => {
    render(<CopyButton text="hello" />);
    const button = screen.getByRole("button", { name: "Copy" });

    await click(button);
    expect(writeText).toHaveBeenCalledWith("hello");
    expect(button).toHaveTextContent("Copied");
    expect(screen.getByRole("status")).toHaveTextContent("Copied to clipboard");

    act(() => vi.advanceTimersByTime(1200));
    expect(button).toHaveTextContent("Copy");
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("restarts the window on a second click instead of flipping back early", async () => {
    render(<CopyButton text="x" />);
    const button = screen.getByRole("button", { name: "Copy" });

    await click(button);
    act(() => vi.advanceTimersByTime(800)); // partway through the first window
    await click(button); // second click — should extend, not stack
    act(() => vi.advanceTimersByTime(800)); // first timer (now cleared) would have fired at 1200
    expect(button).toHaveTextContent("Copied"); // still shown 1600ms after the first click

    act(() => vi.advanceTimersByTime(400)); // 1200ms after the second click
    expect(button).toHaveTextContent("Copy");
  });

  it("cancels the pending timer on unmount", async () => {
    const { unmount } = render(<CopyButton text="x" />);
    await click(screen.getByRole("button", { name: "Copy" }));
    unmount();
    // If the timer weren't cleared, this would fire setState on a gone component.
    expect(() => act(() => vi.advanceTimersByTime(1200))).not.toThrow();
  });
});
