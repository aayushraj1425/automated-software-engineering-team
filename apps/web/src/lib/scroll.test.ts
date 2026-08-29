import { describe, expect, it } from "vitest";

import { isScrolledToBottom } from "./scroll";

describe("isScrolledToBottom", () => {
  it("is true when the container is scrolled to the very bottom", () => {
    expect(isScrolledToBottom({ scrollTop: 900, scrollHeight: 1000, clientHeight: 100 })).toBe(
      true,
    );
  });

  it("is true within the threshold of the bottom (a few pixels off)", () => {
    // 40px from the bottom, default threshold 60 — still following.
    expect(isScrolledToBottom({ scrollTop: 860, scrollHeight: 1000, clientHeight: 100 })).toBe(
      true,
    );
  });

  it("is false when the user has scrolled up past the threshold", () => {
    expect(isScrolledToBottom({ scrollTop: 300, scrollHeight: 1000, clientHeight: 100 })).toBe(
      false,
    );
  });

  it("is true for content that does not overflow the container", () => {
    expect(isScrolledToBottom({ scrollTop: 0, scrollHeight: 100, clientHeight: 100 })).toBe(true);
  });

  it("honors a custom threshold", () => {
    const el = { scrollTop: 850, scrollHeight: 1000, clientHeight: 100 };
    expect(isScrolledToBottom(el, 60)).toBe(true); // 50px off, within 60
    expect(isScrolledToBottom(el, 10)).toBe(false); // 50px off, outside 10
  });
});
