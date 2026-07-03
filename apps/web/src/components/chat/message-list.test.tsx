import { render, screen } from "@testing-library/react";

import { MessageList } from "./message-list";

describe("MessageList", () => {
  it("shows an empty-state hint when there are no messages", () => {
    render(<MessageList messages={[]} />);
    expect(screen.getByText(/Ask ASEP about architecture/)).toBeInTheDocument();
  });

  it("renders user and assistant messages with their content", () => {
    render(
      <MessageList
        messages={[
          { id: "1", role: "user", content: "How does auth work?" },
          { id: "2", role: "assistant", content: "Sessions live in Postgres." },
        ]}
      />,
    );
    expect(screen.getByText("How does auth work?")).toBeInTheDocument();
    expect(screen.getByText("Sessions live in Postgres.")).toBeInTheDocument();
    expect(document.querySelectorAll('[data-role="user"]')).toHaveLength(1);
    expect(document.querySelectorAll('[data-role="assistant"]')).toHaveLength(1);
  });
});
