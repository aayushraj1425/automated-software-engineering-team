// The app-wide error boundary and 404 page: both render a heading and a way
// back, and the boundary's "Try again" re-runs the failed segment.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ErrorBoundary from "@/app/error";
import NotFound from "@/app/not-found";

describe("app error boundary", () => {
  it("shows the message and calls reset when retried", () => {
    const reset = vi.fn();
    render(<ErrorBoundary error={new Error("boom")} reset={reset} />);
    expect(screen.getByRole("heading", { name: "Something went wrong" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(reset).toHaveBeenCalledOnce();
  });
});

describe("not found page", () => {
  it("shows a 404 message and a link home", () => {
    render(<NotFound />);
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to app" })).toHaveAttribute("href", "/");
  });
});
