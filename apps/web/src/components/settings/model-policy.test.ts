import { describe, expect, it } from "vitest";

import { parsePolicy, policyBody } from "./model-policy";

describe("parsePolicy", () => {
  it("reads pins and the open source switch", () => {
    expect(
      parsePolicy({
        level_pins: { principal: "anthropic/claude-fable-5-2", engineer: "anthropic/x" },
        allow_open_source_auto: true,
      }),
    ).toEqual({
      level_pins: { principal: "anthropic/claude-fable-5-2", engineer: "anthropic/x" },
      allow_open_source_auto: true,
    });
  });

  it("drops unknown levels and non-string pins", () => {
    expect(
      parsePolicy({
        level_pins: { wizard: "a/b", senior: 7, support: "" },
        allow_open_source_auto: "yes",
      }),
    ).toEqual({ level_pins: {}, allow_open_source_auto: false });
  });

  it("survives a malformed or empty reply", () => {
    expect(parsePolicy(null)).toEqual({ level_pins: {}, allow_open_source_auto: false });
    expect(parsePolicy("nope")).toEqual({ level_pins: {}, allow_open_source_auto: false });
  });
});

describe("policyBody", () => {
  it("omits levels left on Auto", () => {
    expect(policyBody({ senior: "anthropic/opus", engineer: "" }, true)).toEqual({
      level_pins: { senior: "anthropic/opus" },
      allow_open_source_auto: true,
    });
  });
});
