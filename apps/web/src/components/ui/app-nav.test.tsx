// The nav is the same on every page; only the highlighted link changes with the
// current path, and a nested path (a run detail) still highlights its section.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppNav } from "@/components/ui/app-nav";

const mockPathname = vi.fn<() => string>();

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
}));

vi.mock("@/lib/auth-client", () => ({
  signOut: vi.fn(),
}));

describe("AppNav", () => {
  it("marks the current page as active", () => {
    mockPathname.mockReturnValue("/planning");
    render(<AppNav />);
    expect(screen.getByRole("link", { name: "Planning" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Repositories" })).not.toHaveAttribute("aria-current");
  });

  it("keeps the section active on a nested path", () => {
    mockPathname.mockReturnValue("/runs/abc123");
    render(<AppNav />);
    expect(screen.getByRole("link", { name: "Agent runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
