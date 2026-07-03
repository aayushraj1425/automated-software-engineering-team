import { expect, test } from "@playwright/test";

test("sign up, send a message, receive a streamed reply that persists", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;

  await page.goto("/sign-up");
  await page.getByLabel("Name").fill("E2E Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel(/Password/).fill("super-secret-pw-1");
  await page.getByRole("button", { name: "Create account" }).click();

  await page.waitForURL("**/chat");

  await page.getByPlaceholder("Ask ASEP anything…").fill("hello walking skeleton");
  await page.getByRole("button", { name: "Send" }).click();

  // LLM_FAKE=1 → deterministic canned reply streamed over SSE
  await expect(page.getByText(/canned reply/)).toBeVisible({ timeout: 20_000 });

  // The conversation shows up in the sidebar (persisted server-side)
  await expect(
    page.getByRole("button", { name: /hello walking skeleton/ }),
  ).toBeVisible({ timeout: 10_000 });

  // Reload → history is served from Postgres, not client state
  await page.reload();
  await page.getByRole("button", { name: /hello walking skeleton/ }).click();
  await expect(page.getByText(/canned reply/)).toBeVisible({ timeout: 10_000 });
});
