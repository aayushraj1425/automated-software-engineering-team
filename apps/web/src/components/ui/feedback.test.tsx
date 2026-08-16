// FormError is the app-wide "that action failed" message, adopted across the
// auth flow and every panel — so its contract matters: announce via role="alert",
// render nothing when there's no message, and pass through an extra className.

import { render, screen } from "@testing-library/react";

import { FormError } from "./feedback";

describe("FormError", () => {
  it("shows the message in an alert region for assistive tech", () => {
    render(<FormError message="Sign in failed" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Sign in failed");
  });

  it("renders nothing when the message is null", () => {
    const { container } = render(<FormError message={null} />);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for an empty string", () => {
    render(<FormError message="" />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("merges an extra className onto the message", () => {
    render(<FormError message="Too wide" className="w-full" />);
    expect(screen.getByRole("alert")).toHaveClass("w-full");
  });
});
