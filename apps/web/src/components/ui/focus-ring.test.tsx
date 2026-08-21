// The app promises one visible keyboard-focus indicator on every interactive
// element, applied through the shared primitives. These lock that in: if a
// primitive drops the token, keyboard users lose the focus ring silently, so
// the regression should fail a test instead.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button, buttonClassName } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { focusRing } from "@/components/ui/focus-ring";

describe("focus ring", () => {
  it("uses focus-visible, not focus, so it doesn't show on mouse click", () => {
    expect(focusRing).toContain("focus-visible:ring-2");
    expect(focusRing).not.toMatch(/(^|\s)focus:ring/);
  });

  it("is baked into every button variant's class string", () => {
    for (const variant of ["primary", "secondary", "ghost", "danger"] as const) {
      expect(buttonClassName(variant)).toContain(focusRing);
    }
  });

  it("renders on the Button element", () => {
    render(<Button>Go</Button>);
    expect(screen.getByRole("button", { name: "Go" })).toHaveClass("focus-visible:ring-2");
  });

  it("renders on the CopyButton element", () => {
    render(<CopyButton text="x" />);
    expect(screen.getByRole("button", { name: "Copy" })).toHaveClass("focus-visible:ring-2");
  });
});
