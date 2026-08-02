import { describe, expect, it } from "vitest";

import { agentStyle } from "./agent-style";

describe("agentStyle", () => {
  it("gives each known role its display label and a distinct dot colour", () => {
    expect(agentStyle("product_manager").label).toBe("Product Manager");
    expect(agentStyle("backend").dot).toBe("bg-sky-400");

    const roles = ["product_manager", "backend", "frontend", "devops", "reviewer", "qa"];
    const dots = new Set(roles.map((r) => agentStyle(r).dot));
    expect(dots.size).toBe(roles.length); // no two agents share a colour
  });

  it("falls back to the System style for null or unknown roles", () => {
    expect(agentStyle(null).label).toBe("System");
    expect(agentStyle(null).dot).toBe("bg-zinc-500");
    // an unrecognised role still gets a readable name, but the neutral colour
    expect(agentStyle("mystery").label).toBe("Mystery");
    expect(agentStyle("mystery").dot).toBe("bg-zinc-500");
  });
});
