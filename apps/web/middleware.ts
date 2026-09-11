import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME } from "@/lib/api";

// Every API endpoint these pages call requires auth, so gate them here
// instead of letting each page render an inline 401 error.
const PROTECTED_PREFIXES = [
  "/profile",
  "/foods",
  "/log",
  "/scan",
  "/shopping-list",
  "/water",
  "/supplements",
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
    "/shopping-list/:path*",
    "/water/:path*",
    "/supplements/:path*",
  ],
};
