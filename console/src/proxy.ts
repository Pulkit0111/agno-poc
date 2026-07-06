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
  matcher: ["/((?!api|_next|favicon.ico).*)"],
};
