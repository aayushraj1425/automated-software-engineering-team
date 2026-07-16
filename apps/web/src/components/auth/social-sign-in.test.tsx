// The server decides which providers exist; the buttons only render for
// configured ones, and none configured means no social block at all.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SocialSignIn } from "@/components/auth/social-sign-in";

vi.mock("@/lib/auth-client", () => ({
  authClient: { signIn: { social: vi.fn() } },
}));

describe("SocialSignIn", () => {
  it("renders one button per configured provider", () => {
    render(
      <SocialSignIn
        providers={[
          { id: "github", label: "GitHub" },
          { id: "google", label: "Google" },
        ]}
      />,
    );
    expect(screen.getByRole("button", { name: "Continue with GitHub" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue with Microsoft" })).toBeNull();
  });

  it("renders nothing when no provider is configured", () => {
    const { container } = render(<SocialSignIn providers={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
