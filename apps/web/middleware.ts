import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME } from "@/lib/api";

// Every API endpoint these pages call requires auth, so gate them here
// instead of letting each page render an inline 401 error.
const PROTECTED_PREFIXES = [
  "/profile",
  "/foods",
  "/log",
  "/scan",
  "/chat",
  "/shopping-list",
  "/pantry",
  "/water",
  "/supplements",
  "/diet-plans",
  "/recipes",
  "/wearables",
  "/security",
  "/household",
  "/progress",
  "/admin",
  "/consent",
  "/ayuno",
  "/calculadoras",
  "/recordatorios",
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
  if (!isProtected) return NextResponse.next();

  if (!request.cookies.has(SESSION_COOKIE_NAME)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/profile/:path*",
    "/foods/:path*",
    "/log/:path*",
    "/scan/:path*",
    "/chat/:path*",
    "/consent/:path*",
    "/shopping-list/:path*",
    "/pantry/:path*",
    "/water/:path*",
    "/supplements/:path*",
    "/diet-plans/:path*",
    "/recipes/:path*",
    "/wearables/:path*",
    "/security/:path*",
    "/household/:path*",
    "/progress/:path*",
    "/admin/:path*",
    "/ayuno/:path*",
    "/calculadoras/:path*",
    "/recordatorios/:path*",
  ],
};
