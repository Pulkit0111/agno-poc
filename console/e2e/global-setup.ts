import { execSync } from "child_process";
import path from "path";
import type { FullConfig } from "@playwright/test";

async function globalSetup(_config: FullConfig) {
  // Mints a real HMAC session token by calling the backend's own session issuer directly —
  // there is no HTTP backdoor for this. Requires CONSOLE_SESSION_SECRET to be set in THIS
  // shell's environment, matching whatever the running `uv run bott-app` process uses.
  const repoRoot = path.resolve(__dirname, "../..");
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
  await context.storageState({ path: path.join(__dirname, ".auth-state.json") });
  await browser.close();
}

export default globalSetup;
