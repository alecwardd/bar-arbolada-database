import type { NextRequest } from "next/server";
import { resolveManagerAccess } from "../../lib/manager-access";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const access = resolveManagerAccess(request);
  if (!access) {
    return Response.json(
      { message: "You are not authorized to view Bar Arbolada analytics." },
      { status: 403, headers: { "cache-control": "private, no-store" } },
    );
  }

  return Response.json(
    { role: access.role },
    { headers: { "cache-control": "private, no-store" } },
  );
}
