// WorkspaceShell frames every signed-in page. Its load-bearing a11y contract:
// the page body is a <main> landmark carrying the id the layout's skip link
// targets (and a tabIndex so focus can land there). Lock that in, plus the title.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MAIN_CONTENT_ID } from "./main-content";
import { WorkspaceShell } from "./workspace-shell";

// The nav is exercised by app-nav.test; here it just needs its hooks stubbed so
// the real shell renders.
vi.mock("next/navigation", () => ({ usePathname: () => "/runs" }));
vi.mock("@/lib/auth-client", () => ({ signOut: vi.fn() }));

describe("WorkspaceShell", () => {
  it("renders the title and children inside the skip-link target landmark", () => {
    render(
      <WorkspaceShell title="Agent runs">
        <p>panel body</p>
      </WorkspaceShell>,
    );
    expect(screen.getByRole("heading", { name: "Agent runs" })).toBeInTheDocument();
    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", MAIN_CONTENT_ID);
    expect(main).toHaveAttribute("tabindex", "-1");
    expect(main).toHaveTextContent("panel body");
  });

  it("renders the action beside the title", () => {
    render(
      <WorkspaceShell title="Run detail" action={<button type="button">All runs</button>}>
        <p>body</p>
      </WorkspaceShell>,
    );
    expect(screen.getByRole("button", { name: "All runs" })).toBeInTheDocument();
  });
});
