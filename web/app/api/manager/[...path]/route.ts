import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const ALLOWED_PATHS = new Set([
  "overview",
  "daily-sales",
  "staffing-rush",
  "profitability",
  "inventory/health",
  "import-operations",
]);

function json(message: string, status: number) {
  return Response.json(
    { message },
    {
      status,
      headers: {
        "cache-control": "private, no-store",
      },
    },
  );
}

function authorizedWorkspaceUser(request: NextRequest): boolean {
  if (process.env.NODE_ENV !== "production") return true;
  const email = request.headers.get("oai-authenticated-user-email");
  if (!email) return false;

  const allowlist = (process.env.BAR_MANAGER_EMAILS ?? "")
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);

  return allowlist.length === 0 || allowlist.includes(email.toLowerCase());
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  if (
    process.env.NODE_ENV === "production" &&
    request.headers.get("sec-fetch-site") === "cross-site"
  ) {
    return json("Cross-site analytics requests are not allowed.", 403);
  }

  const origin = request.headers.get("origin");
  if (origin && origin !== request.nextUrl.origin) {
    return json("Cross-origin analytics requests are not allowed.", 403);
  }

  if (!authorizedWorkspaceUser(request)) {
    return json("You are not authorized to view Bar Arbolada analytics.", 403);
  }

  const { path } = await context.params;
  const resource = path.join("/");
  if (!ALLOWED_PATHS.has(resource)) {
    return json("This analytics resource is not available.", 404);
  }

  const apiBase = process.env.BAR_API_BASE_URL?.replace(/\/+$/, "");
  const apiToken = process.env.MANAGER_API_TOKEN;
  const accessClientId = process.env.CF_ACCESS_CLIENT_ID;
  const accessClientSecret = process.env.CF_ACCESS_CLIENT_SECRET;
  if (!apiBase || !apiToken) {
    return json("The private analytics connection has not been configured.", 503);
  }
  if (process.env.NODE_ENV === "production" && !apiBase.startsWith("https://")) {
    return json("The private analytics connection is not using HTTPS.", 503);
  }

  const target = new URL(`${apiBase}/api/v1/${resource}`);
  request.nextUrl.searchParams.forEach((value, key) => {
    target.searchParams.append(key, value);
  });

  try {
    const headers: Record<string, string> = {
      accept: "application/json",
      authorization: `Bearer ${apiToken}`,
    };
    if (accessClientId && accessClientSecret) {
      headers["CF-Access-Client-Id"] = accessClientId;
      headers["CF-Access-Client-Secret"] = accessClientSecret;
    }

    const upstream = await fetch(target, {
      method: "GET",
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(12_000),
    });

    const body = await upstream.text();
    return new Response(body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        "cache-control": "private, no-store",
        "x-content-type-options": "nosniff",
      },
    });
  } catch {
    return json("The local analytics service is temporarily unavailable.", 502);
  }
}
