import { NextRequest, NextResponse } from "next/server";

// Presence check only — the API verifies the signature on every call.
export function proxy(req: NextRequest) {
  const hasSession = req.cookies.has("bott_console_session");
  const isLogin = req.nextUrl.pathname === "/login";
  if (!hasSession && !isLogin) {
    return NextResponse.redirect(new URL("/login", req.url));
  }
  if (hasSession && isLogin) {
    return NextResponse.redirect(new URL("/", req.url));
  }
  return NextResponse.next();
}

export const config = {
  // /slack and /webhook are excluded like /api: they are proxied straight to
  // the Python backend (see next.config.ts rewrites) and authenticated there
  // (Slack signing secret / GitHub webhook secret), so the console's
  // session-cookie gate must not intercept them.
  matcher: ["/((?!api|slack|webhook|_next|favicon.ico).*)"],
};
