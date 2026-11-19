import { describe, expect, it } from "vitest";

import { isPinned, levelName, modelOptions, seatLabel, shortModel, withOverride } from "./roster";
import type { CatalogModel } from "./types";

function model(overrides: Partial<CatalogModel> & { id: string }): CatalogModel {
  return {
    provider: overrides.id.split("/")[0],
    context_size: 200000,
    supports_tools: true,
    strength: 3,
    input_cost_per_million: 3,
    output_cost_per_million: 15,
    open_source: false,
    evaluated: false,
    ...overrides,
  };
}

describe("modelOptions", () => {
  const catalog = [
    model({ id: "anthropic/claude-sonnet-5-5", strength: 3 }),
    model({ id: "anthropic/claude-fable-5-2", strength: 5, input_cost_per_million: 15 }),
    model({ id: "anthropic/claude-opus-5-5", strength: 4 }),
    model({ id: "anthropic/claude-haiku-5-5", strength: 1, input_cost_per_million: 1 }),
    model({ id: "anthropic/no-tools", strength: 5, supports_tools: false }),
  ];

  it("drops models that cannot call tools and sorts strongest first", () => {
    const ids = modelOptions(catalog).map((option) => option.id);
    expect(ids).toEqual([
      "anthropic/claude-fable-5-2",
      "anthropic/claude-opus-5-5",
      "anthropic/claude-sonnet-5-5",
      "anthropic/claude-haiku-5-5",
    ]);
  });

  it("breaks strength ties by cheapest first", () => {
    const ids = modelOptions([
      model({ id: "openai/pricey", strength: 4, input_cost_per_million: 30 }),
      model({ id: "openai/cheap", strength: 4, input_cost_per_million: 1 }),
    ]).map((option) => option.id);
    expect(ids).toEqual(["openai/cheap", "openai/pricey"]);
  });

  it("does not mutate the catalog it was given", () => {
    const copy = catalog.map((entry) => entry.id);
    modelOptions(catalog);
    expect(catalog.map((entry) => entry.id)).toEqual(copy);
  });

  it("labels strength and price, and flags unevaluated open source models", () => {
    const [option] = modelOptions([
      model({
        id: "openai/llama-local",
        open_source: true,
        evaluated: false,
        strength: 2,
        input_cost_per_million: 0,
        output_cost_per_million: 0,
      }),
    ]);
    expect(option.label).toContain("llama-local");
    expect(option.label).toContain("strength 2");
    expect(option.label).toContain("not evaluated");
  });

  it("keeps the seat's current model even when the catalog lacks it", () => {
    const options = modelOptions(catalog, "anthropic/retired-model");
    expect(options[0]).toEqual({
      id: "anthropic/retired-model",
      label: "retired-model (not in the catalog)",
    });
  });

  it("does not duplicate a current model the catalog already lists", () => {
    const options = modelOptions(catalog, "anthropic/claude-opus-5-5");
    expect(options.filter((option) => option.id === "anthropic/claude-opus-5-5")).toHaveLength(1);
  });
});

describe("withOverride", () => {
  it("adds a pin without touching the original map", () => {
    const original = { "backend:engineer": "anthropic/a" };
    const next = withOverride(original, "reviewer:senior", "anthropic/b");
    expect(next).toEqual({ "backend:engineer": "anthropic/a", "reviewer:senior": "anthropic/b" });
    expect(original).toEqual({ "backend:engineer": "anthropic/a" });
  });

  it("treats an empty choice as Auto and removes the pin", () => {
    expect(withOverride({ "backend:engineer": "anthropic/a" }, "backend:engineer", "")).toEqual({});
  });
});

describe("labels", () => {
  it("names seats and levels", () => {
    expect(seatLabel("principal_engineer:principal")).toBe("Principal Engineer (Principal)");
    expect(seatLabel("backend:engineer")).toBe("Backend (Engineer)");
    expect(seatLabel("qa")).toBe("Qa");
    expect(levelName("senior")).toBe("Senior");
    expect(levelName("mystery")).toBe("Mystery");
  });

  it("shortens provider-prefixed model ids", () => {
    expect(shortModel("anthropic/claude-opus-5-5")).toBe("claude-opus-5-5");
    expect(shortModel(null)).toBe("auto");
  });

  it("knows which seats are pinned by hand", () => {
    const seat = { key: "backend:engineer", role: "backend", level: "engineer", reason: "" };
    expect(isPinned(seat, { "backend:engineer": "x" })).toBe(true);
    expect(isPinned(seat, {})).toBe(false);
  });
});
