import { expect, test } from "@playwright/test";

// Extended smoke: Home shows the model card, then a tour through Todos and
// Skills. Approving a seeded approval from Home is already covered by
// approvals.spec.ts — this file picks up the rest of the brief's flow.

test("Home shows the model card", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/ChatGPT \(Codex\)/)).toBeVisible();
});

test("create a todo and see it appear", async ({ page }) => {
  const text = `E2E todo ${Date.now()}`;

  await page.goto("/todos");
  await expect(page.getByRole("heading", { name: "Todos" })).toBeVisible();

  await page.getByLabel("Add a todo").fill(text);
  await page.getByRole("button", { name: "Add" }).click();

  await expect(page.getByText(text)).toBeVisible();
});

test("open a skill's detail page and see rendered content", async ({ page }) => {
  await page.goto("/skills");
  await expect(page.getByRole("heading", { name: "Skills" })).toBeVisible();

  // Exclude the "New skill" link (also matches the `/skills/` prefix) — we want an
  // actual skill card from the grid below the filter bar.
  const firstCard = page.locator('a[href^="/skills/"]:not([href="/skills/new"])').first();
  const name = (await firstCard.locator("span.font-semibold").first().textContent())?.trim();
  await firstCard.click();

  await expect(page).toHaveURL(/\/skills\/[^/]+$/);
  if (name) await expect(page.getByText(name, { exact: true }).first()).toBeVisible();

  // The rendered-markdown body card is present and non-empty.
  const body = page.locator(".rounded-xl.border.bg-card.p-5.shadow-sm");
  await expect(body).toBeVisible();
  await expect(body).not.toBeEmpty();
});
