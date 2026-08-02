import { describe, expect, it } from "vitest";

import { parseUnifiedDiff } from "./parse-diff";

const SAMPLE = `diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
 import os
-x = 1
+x = 2
+y = 3
diff --git a/README.md b/README.md
index 3333333..4444444 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
`;

describe("parseUnifiedDiff", () => {
  it("splits into one section per file with the right paths and ± counts", () => {
    const files = parseUnifiedDiff(SAMPLE);
    expect(files.map((f) => f.path)).toEqual(["src/app.py", "README.md"]);
    expect(files[0]).toMatchObject({ additions: 2, deletions: 1 });
    expect(files[1]).toMatchObject({ additions: 1, deletions: 1 });
    expect(files[0].body).toContain("+x = 2");
    expect(files[0].body).not.toContain("README"); // sections don't bleed
  });

  it("reads the path off the header for a deletion (no +++ b/ path)", () => {
    const deletion = `diff --git a/gone.txt b/gone.txt
deleted file mode 100644
index 5555555..0000000
--- a/gone.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
`;
    const [file] = parseUnifiedDiff(deletion);
    expect(file.path).toBe("gone.txt");
    expect(file.deletions).toBe(1);
  });

  it("returns [] for empty or whitespace input", () => {
    expect(parseUnifiedDiff("")).toEqual([]);
    expect(parseUnifiedDiff("   \n  ")).toEqual([]);
  });
});
