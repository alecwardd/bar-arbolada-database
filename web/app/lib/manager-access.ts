import type { NextRequest } from "next/server";

export type ManagerRole = "viewer" | "manager" | "owner";
export type ManagerAccess = { email: string; role: ManagerRole };

export function resolveManagerAccess(request: NextRequest): ManagerAccess | null {
  if (process.env.NODE_ENV !== "production") {
    return { email: "local-development", role: "owner" };
  }

  const email = request.headers.get("oai-authenticated-user-email");
  if (!email) return null;
  const normalizedEmail = email.trim().toLowerCase();

  const roles = new Map<string, ManagerRole>();
  for (const entry of (process.env.BAR_MANAGER_ROLES ?? "").split(",")) {
    const [configuredEmail, configuredRole] = entry.split("=", 2);
    const role = configuredRole?.trim().toLowerCase();
    if (
      configuredEmail?.trim() &&
      (role === "viewer" || role === "manager" || role === "owner")
    ) {
      roles.set(configuredEmail.trim().toLowerCase(), role);
    }
  }

  for (const configuredEmail of (process.env.BAR_MANAGER_EMAILS ?? "")
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean)) {
    if (!roles.has(configuredEmail)) roles.set(configuredEmail, "manager");
  }

  const role = roles.get(normalizedEmail);
  return role ? { email: normalizedEmail, role } : null;
}
