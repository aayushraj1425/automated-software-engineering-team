import { render, screen } from "@testing-library/react";

import { DependencyGraphView } from "./dependency-graph";

describe("DependencyGraphView", () => {
  it("draws a node per connected file and a line per import", () => {
    const { container } = render(
      <DependencyGraphView
        graph={{
          nodes: [
            { path: "app/main.py", language: "python", in_degree: 1, out_degree: 1 },
            { path: "app/config.py", language: "python", in_degree: 1, out_degree: 0 },
            { path: "tests/test_app.py", language: "python", in_degree: 0, out_degree: 1 },
          ],
          edges: [
            { source: "app/main.py", target: "app/config.py" },
            { source: "tests/test_app.py", target: "app/main.py" },
          ],
        }}
      />,
    );

    expect(screen.getByText("main.py")).toBeInTheDocument();
    expect(screen.getByText("config.py")).toBeInTheDocument();
    expect(container.querySelectorAll("circle")).toHaveLength(3);
    expect(container.querySelectorAll("line")).toHaveLength(2);
    expect(container.textContent).toContain("3 connected files · 2 imports");
  });

  it("shows a plain message when there are no import relationships", () => {
    render(
      <DependencyGraphView
        graph={{
          nodes: [{ path: "README.md", language: "markdown", in_degree: 0, out_degree: 0 }],
          edges: [],
        }}
      />,
    );
    expect(screen.getByText(/No import relationships found/)).toBeInTheDocument();
  });
});
