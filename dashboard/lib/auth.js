import { SignJWT, jwtVerify } from "jose";

const JWT_SECRET = new TextEncoder().encode(
  process.env.JWT_SECRET || "verixio-dev-secret-change-in-production"
);

const ENTERPRISE_URL = process.env.ENTERPRISE_URL || "http://localhost:9300";

const ADMIN_USER = process.env.ADMIN_USER || "admin";
const ADMIN_PASS = process.env.ADMIN_PASS || "admin";

const TOKEN_EXPIRY = process.env.TOKEN_EXPIRY || "8h";

const ROLE_HIERARCHY = { admin: 3, operator: 2, viewer: 1 };

const PERMISSIONS = {
  "system:read": "viewer",
  "system:write": "operator",
  "system:admin": "admin",
  "agents:read": "viewer",
  "agents:write": "operator",
  "agents:delete": "admin",
  "tasks:read": "viewer",
  "tasks:write": "operator",
  "tasks:delete": "admin",
  "pipeline:read": "viewer",
  "pipeline:execute": "operator",
  "pipeline:admin": "admin",
  "prospects:read": "viewer",
  "prospects:write": "operator",
  "billing:read": "operator",
  "billing:write": "admin",
  "audit:read": "operator",
  "audit:admin": "admin",
  "apikeys:read": "admin",
  "apikeys:write": "admin",
  "users:read": "admin",
  "users:write": "admin",
  "export:read": "operator",
  "config:read": "operator",
  "config:write": "admin",
};

export function hasPermission(userRole, permission) {
  const requiredRole = PERMISSIONS[permission] || "admin";
  return (ROLE_HIERARCHY[userRole] || 0) >= (ROLE_HIERARCHY[requiredRole] || 3);
}

export function getUserPermissions(role) {
  return Object.keys(PERMISSIONS).filter((perm) => hasPermission(role, perm));
}

export async function createToken(username, role = "admin", displayName = "") {
  return new SignJWT({
    sub: username,
    role,
    display_name: displayName || username,
    permissions: getUserPermissions(role),
  })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(TOKEN_EXPIRY)
    .sign(JWT_SECRET);
}

export async function verifyToken(token) {
  try {
    const { payload } = await jwtVerify(token, JWT_SECRET);
    return payload;
  } catch {
    return null;
  }
}

export async function validateCredentials(username, password) {
  try {
    const resp = await fetch(`${ENTERPRISE_URL}/admin/users/authenticate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (resp.ok) {
      return await resp.json();
    }
  } catch {
    // Fall back to local credentials
  }

  if (username === ADMIN_USER && password === ADMIN_PASS) {
    return { ok: 1, username, role: "admin", display_name: "Admin" };
  }
  return null;
}
