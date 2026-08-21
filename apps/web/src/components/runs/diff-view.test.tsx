// The diff viewer is a set of disclosures: each file section reports its
// expanded state to assistive tech, and toggling it flips that state and the
// visible body. A single file (defaultOpen when files.length <= 3) starts open.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DiffView } from "@/components/runs/diff-view";

const DIFF = `diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
-x = 1
+x = 2
`;

describe("DiffView", () => {
  it("renders nothing for an empty diff", () => {
    const { container } = render(<DiffView diff="" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("exposes each file section as a disclosure and toggles it", () => {
    render(<DiffView diff={DIFF} />);
    const toggle = screen.getByRole("button", { name: /src\/app\.py/ });

    // One file, so it starts open (defaultOpen when files.length <= 3).
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("+x = 2")).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("+x = 2")).not.toBeInTheDocument();
  });
});
