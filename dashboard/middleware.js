import { NextResponse } from "next/server";
import { jwtVerify } from "jose";

const JWT_SECRET = new TextEncoder().encode(
  process.env.JWT_SECRET || "verixio-dev-secret-change-in-production"
);

const PUBLIC_PATHS = ["/login", "/api/auth"];

const ROLE_HIERARCHY = { admin: 3, operator: 2, viewer: 1 };

const PROTECTED_ROUTES = {
  "/admin": "admin",
  "/api/admin": "admin",
  "/api/audit": "operator",
};

export async function middleware(request) {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  if (pathname.startsWith("/_next") || pathname.startsWith("/favicon")) {
    return NextResponse.next();
  }

  const token = request.cookies.get("token")?.value;

  if (!token) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.redirect(new URL("/login", request.url));
  }

  try {
    const { payload } = await jwtVerify(token, JWT_SECRET);

    const userRole = payload.role || "viewer";
    for (const [route, requiredRole] of Object.entries(PROTECTED_ROUTES)) {
      if (pathname.startsWith(route)) {
        const userLevel = ROLE_HIERARCHY[userRole] || 0;
        const requiredLevel = ROLE_HIERARCHY[requiredRole] || 3;
        if (userLevel < requiredLevel) {
          if (pathname.startsWith("/api/")) {
            return NextResponse.json(
              { error: "Insufficient permissions", required_role: requiredRole },
              { status: 403 }
            );
          }
          return NextResponse.redirect(new URL("/", request.url));
        }
      }
    }

    const response = NextResponse.next();
    response.headers.set("X-User-Role", userRole);
    response.headers.set("X-User-Id", payload.sub || "unknown");
    return response;
  } catch {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "Token expired" }, { status: 401 });
    }
    const response = NextResponse.redirect(new URL("/login", request.url));
    response.cookies.set("token", "", { maxAge: 0 });
    return response;
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
