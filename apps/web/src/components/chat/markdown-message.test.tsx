import { render, screen } from "@testing-library/react";

import { MarkdownMessage } from "./markdown-message";

describe("MarkdownMessage", () => {
  it("renders a fenced code block with its language and a copy button", () => {
    render(<MarkdownMessage content={"Here:\n\n```python\nprint('hi')\n```"} />);
    expect(screen.getByText("Here:")).toBeInTheDocument();
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("keeps inline code inline, with no code-block chrome", () => {
    render(<MarkdownMessage content={"Use the `router` seam."} />);
    expect(screen.getByText("router")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /copy/i })).not.toBeInTheDocument();
  });
});
