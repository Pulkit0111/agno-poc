import { execSync } from "child_process";
import path from "path";
import { expect, test } from "@playwright/test";

function seedApproval(summary: string): void {
  const repoRoot = path.resolve(__dirname, "../..");
  execSync(
    `uv run python -c "from bott.shared import approvals; approvals.init_approvals(); ` +
    `approvals.create_request('e2e@axelerant.com', 'api:jira', '${summary}')"`,
    { cwd: repoRoot },
  );
}

test("approve a pending approval removes it from the pending list", async ({ page }) => {
  const summary = `E2E smoke ${Date.now()}`;
  seedApproval(summary);

  await page.goto("/approvals");
  await expect(page.getByText(summary)).toBeVisible();

  await page
    .locator("div.border-b")
    .filter({ hasText: summary })
    .getByRole("button", { name: "Approve" })
    .click();

  await expect(page.getByText(summary)).not.toBeVisible();
});
