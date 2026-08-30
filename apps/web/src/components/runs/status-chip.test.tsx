// The status chip colour-codes a status and humanizes its id for display. It's
// shared by runs, repositories, and the planning board, so it must cover the
// work-item states too — not just run/task ones — and read cleanly for a
// multi-word status.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusChip } from "@/components/runs/status-chip";

describe("StatusChip", () => {
  it("gives the work-item states their own colours, not the default gray", () => {
    const { rerender } = render(<StatusChip status="proposed" />);
    expect(screen.getByText("proposed").className).toContain("text-blue-300");

    rerender(<StatusChip status="ready" />);
    expect(screen.getByText("ready").className).toContain("text-teal-300");
  });

  it("humanizes every underscore in a status id", () => {
    render(<StatusChip status="awaiting_approval" />);
    expect(screen.getByText("awaiting approval")).toBeInTheDocument();
  });

  it("falls back to a neutral gray for an unknown status", () => {
    render(<StatusChip status="something_new" />);
    const chip = screen.getByText("something new");
    expect(chip.className).toContain("bg-zinc-800");
  });
});
