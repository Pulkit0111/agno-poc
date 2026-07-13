import { execSync } from "child_process";
import path from "path";
import type { FullConfig } from "@playwright/test";

// eslint-disable-next-line @typescript-eslint/no-unused-vars -- required by Playwright's globalSetup signature
async function globalSetup(_config: FullConfig) {
  // Mints a real HMAC session token by calling the backend's own session issuer directly —
  // there is no HTTP backdoor for this. Requires CONSOLE_SESSION_SECRET to be set in THIS
  // shell's environment, matching whatever the running `uv run bott-app` process uses.
  const repoRoot = path.resolve(__dirname, "../..");

  // The session's is_admin claim is only a CLAIM — sessions.verify_session recomputes
  // is_admin live from bott.shared.roles (env BOTT_ADMINS ∪ KV-promoted roles) on every
  // request (by design, see sessions.py). So the e2e user must actually BE an admin (in
  // the same DB the running backend reads, via AGENTOS_DB_PATH) for the admin-only bits
  // of the smoke (deciding an approval) to render their controls at all.
  execSync(
    `uv run python -c "from bott.shared import roles; roles.set_role('e2e@axelerant.com', 'admin', 'e2e-seed')"`,
    { cwd: repoRoot },
  );

  const token = execSync(
    `uv run python -c "from bott.interfaces.console.sessions import issue_session; print(issue_session('e2e@axelerant.com', True))"`,
    { cwd: repoRoot, encoding: "utf-8" },
  ).trim();

  const { chromium } = await import("@playwright/test");
  const browser = await chromium.launch();
  const context = await browser.newContext();
  await context.addCookies([{
    name: "bott_console_session",
    value: token,
    domain: "localhost",
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
  }]);

  // Pre-dismiss the one-time "Welcome to the Bott Console" modal (localStorage-gated,
  // see components/common/welcome.tsx) so it never intercepts clicks in the specs below —
  // it has nothing to do with what those specs are exercising.
  const page = await context.newPage();
  await page.goto("http://localhost:3000/");
  await page.evaluate(() => localStorage.setItem("bott.welcome.seen", "1"));
  await page.close();

  await context.storageState({ path: path.join(__dirname, ".auth-state.json") });
  await browser.close();
}

export default globalSetup;
