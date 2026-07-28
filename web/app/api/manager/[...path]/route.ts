import { createHmac, randomUUID } from "node:crypto";
import type { NextRequest } from "next/server";
import { resolveManagerAccess } from "../../../lib/manager-access";

export const dynamic = "force-dynamic";

const ALLOWED_PATHS = new Set([
  "overview",
  "daily-sales",
  "staffing-rush",
  "profitability",
  "inventory/health",
  "import-operations",
]);
const MAX_UPSTREAM_BYTES = 2_000_000;

function json(message: string, status: number, requestId?: string) {
  return Response.json(
    { message },
    {
      status,
      headers: {
        "cache-control": "private, no-store",
        ...(requestId ? { "x-request-id": requestId } : {}),
      },
    },
  );
}

function auditActor(email: string): string | null {
  const key = process.env.BAR_AUDIT_HASH_KEY;
  if (!key) return null;
  return createHmac("sha256", key).update(email).digest("hex").slice(0, 24);
}

function auditRead(
  requestId: string,
  email: string,
  role: string,
  resource: string,
  status: number,
  startedAt: number,
) {
  const actor = auditActor(email);
  if (!actor) return;
  console.info(
    JSON.stringify({
      event: "manager_api_read",
      request_id: requestId,
      actor,
      role,
      resource,
      status,
      duration_ms: Date.now() - startedAt,
    }),
  );
}

async function readBoundedBody(response: Response): Promise<Uint8Array> {
  const declaredLength = Number(response.headers.get("content-length") ?? "0");
  if (declaredLength > MAX_UPSTREAM_BYTES) {
    throw new Error("Manager API response exceeded the size limit.");
  }
  if (!response.body) return new Uint8Array();

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    received += value.byteLength;
    if (received > MAX_UPSTREAM_BYTES) {
      await reader.cancel();
      throw new Error("Manager API response exceeded the size limit.");
    }
    chunks.push(value);
  }

  const body = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const requestId = randomUUID();
  const startedAt = Date.now();

  if (
    process.env.NODE_ENV === "production" &&
    request.headers.get("sec-fetch-site") === "cross-site"
  ) {
    return json("Cross-site analytics requests are not allowed.", 403, requestId);
  }

  const origin = request.headers.get("origin");
  if (origin && origin !== request.nextUrl.origin) {
    return json("Cross-origin analytics requests are not allowed.", 403, requestId);
  }

  const access = resolveManagerAccess(request);
  if (!access) {
    return json(
      "You are not authorized to view Bar Arbolada analytics.",
      403,
      requestId,
    );
  }

  const { path } = await context.params;
  const resource = path.join("/");
  if (!ALLOWED_PATHS.has(resource)) {
    return json("This analytics resource is not available.", 404, requestId);
  }

  const apiBase = process.env.BAR_API_BASE_URL?.replace(/\/+$/, "");
  const apiToken = process.env.MANAGER_API_TOKEN;
  const auditHashKey = process.env.BAR_AUDIT_HASH_KEY;
  const accessClientId = process.env.CF_ACCESS_CLIENT_ID;
  const accessClientSecret = process.env.CF_ACCESS_CLIENT_SECRET;
  if (
    !apiBase ||
    !apiToken ||
    (process.env.NODE_ENV === "production" &&
      (!auditHashKey || !accessClientId || !accessClientSecret))
  ) {
    return json(
      "The private analytics connection has not been configured.",
      503,
      requestId,
    );
  }
  if (process.env.NODE_ENV === "production" && !apiBase.startsWith("https://")) {
    return json(
      "The private analytics connection is not using HTTPS.",
      503,
      requestId,
    );
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

    const upstreamContentType = upstream.headers.get("content-type") ?? "";
    if (!upstreamContentType.toLowerCase().includes("application/json")) {
      auditRead(requestId, access.email, access.role, resource, 502, startedAt);
      return json(
        "The local analytics service returned an invalid response.",
        502,
        requestId,
      );
    }

    const body = await readBoundedBody(upstream);
    auditRead(
      requestId,
      access.email,
      access.role,
      resource,
      upstream.status,
      startedAt,
    );
    return new Response(body, {
      status: upstream.status,
      headers: {
        "content-type": upstreamContentType,
        "cache-control": "private, no-store",
        "x-content-type-options": "nosniff",
        "x-request-id": requestId,
      },
    });
  } catch {
    auditRead(requestId, access.email, access.role, resource, 502, startedAt);
    return json(
      "The local analytics service is temporarily unavailable.",
      502,
      requestId,
    );
  }
}
