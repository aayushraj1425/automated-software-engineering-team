import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TeamRoster } from "./team-roster";
import type { CatalogModel, TeamSeat } from "./types";

const team: TeamSeat[] = [
  {
    key: "principal_engineer:principal",
    role: "principal_engineer",
    level: "principal",
    model: "anthropic/claude-fable-5-2",
    reason: "auto: cheapest at strength 5",
  },
  {
    key: "backend:engineer",
    role: "backend",
    level: "engineer",
    model: "anthropic/claude-sonnet-5-5",
    reason: "pinned by you",
  },
];

const catalog: CatalogModel[] = [
  {
    id: "anthropic/claude-fable-5-2",
    provider: "anthropic",
    context_size: 200000,
    supports_tools: true,
    strength: 5,
    input_cost_per_million: 15,
    output_cost_per_million: 75,
    open_source: false,
    evaluated: false,
  },
  {
    id: "anthropic/claude-sonnet-5-5",
    provider: "anthropic",
    context_size: 200000,
    supports_tools: true,
    strength: 3,
    input_cost_per_million: 3,
    output_cost_per_million: 15,
    open_source: false,
    evaluated: false,
  },
  {
    id: "anthropic/text-only",
    provider: "anthropic",
    context_size: 8000,
    supports_tools: false,
    strength: 5,
    input_cost_per_million: 1,
    output_cost_per_million: 1,
    open_source: false,
    evaluated: false,
  },
];

function renderRoster(props: Partial<React.ComponentProps<typeof TeamRoster>> = {}) {
  const onChange = vi.fn();
  render(
    <TeamRoster
      team={team}
      overrides={{ "backend:engineer": "anthropic/claude-sonnet-5-5" }}
      catalog={catalog}
      catalogError={null}
      editable
      busy={false}
      error={null}
      onChange={onChange}
      {...props}
    />,
  );
  return onChange;
}

describe("TeamRoster", () => {
  it("shows each seat's key, role, level, model and reason", () => {
    renderRoster({ editable: false });
    expect(screen.getByText("principal_engineer:principal")).toBeInTheDocument();
    expect(screen.getByText("Principal Engineer")).toBeInTheDocument();
    expect(screen.getByText("claude-fable-5-2")).toBeInTheDocument();
    expect(screen.getByText("auto: cheapest at strength 5")).toBeInTheDocument();
    expect(screen.getByText("pinned by you")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("offers only tool-capable catalog models in a seat's select", () => {
    renderRoster();
    const select = screen.getByLabelText("Model for backend:engineer") as HTMLSelectElement;
    const values = Array.from(select.options).map((option) => option.value);
    expect(values).toEqual(["", "anthropic/claude-fable-5-2", "anthropic/claude-sonnet-5-5"]);
    expect(select.value).toBe("anthropic/claude-sonnet-5-5");
  });

  it("sends the whole override map when a model is picked", () => {
    const onChange = renderRoster();
    fireEvent.change(screen.getByLabelText("Model for principal_engineer:principal"), {
      target: { value: "anthropic/claude-sonnet-5-5" },
    });
    expect(onChange).toHaveBeenCalledWith({
      "backend:engineer": "anthropic/claude-sonnet-5-5",
      "principal_engineer:principal": "anthropic/claude-sonnet-5-5",
    });
  });

  it("picking Auto drops that seat from the map", () => {
    const onChange = renderRoster();
    fireEvent.change(screen.getByLabelText("Model for backend:engineer"), {
      target: { value: "" },
    });
    expect(onChange).toHaveBeenCalledWith({});
  });

  it("resets every override with an empty map", () => {
    const onChange = renderRoster();
    fireEvent.click(screen.getByRole("button", { name: "Reset all to auto" }));
    expect(onChange).toHaveBeenCalledWith({});
  });

  it("disables reset when nothing is pinned", () => {
    renderRoster({ overrides: {} });
    expect(screen.getByRole("button", { name: "Reset all to auto" })).toBeDisabled();
  });

  it("locks the selects and explains why when the catalog failed to load", () => {
    renderRoster({ catalog: null, catalogError: "HTTP 502" });
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText(/Model choices are unavailable: HTTP 502/)).toBeInTheDocument();
  });

  it("shows the engine's refusal next to the roster", () => {
    renderRoster({ error: "Unknown seat key" });
    expect(screen.getByText("Unknown seat key")).toBeInTheDocument();
  });

  it("disables the selects while a change is saving", () => {
    renderRoster({ busy: true });
    expect(screen.getByLabelText("Model for backend:engineer")).toBeDisabled();
  });

  it("renders nothing for a run without a team", () => {
    const { container } = render(
      <TeamRoster
        team={[]}
        overrides={{}}
        catalog={catalog}
        catalogError={null}
        editable
        busy={false}
        error={null}
        onChange={() => {}}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
