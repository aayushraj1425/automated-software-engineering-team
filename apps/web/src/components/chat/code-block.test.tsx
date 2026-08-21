import { fireEvent, render, screen } from "@testing-library/react";

import { CodeBlock } from "./code-block";

describe("CodeBlock", () => {
  it("shows the language label and a copy button", () => {
    render(<CodeBlock code="print('hi')" language="python" />);
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("collapses a long block behind a show-more toggle that reports its state", () => {
    const long = Array.from({ length: 40 }, (_, i) => `line ${i}`).join("\n");
    render(<CodeBlock code={long} language="text" />);
    const toggle = screen.getByRole("button", { name: /show \d+ more lines/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: /show less/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("leaves a short block fully expanded (no toggle)", () => {
    render(<CodeBlock code={"a\nb\nc"} language="text" />);
    expect(screen.queryByRole("button", { name: /more lines/i })).not.toBeInTheDocument();
  });
});
