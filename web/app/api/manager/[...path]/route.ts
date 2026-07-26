import { createHmac, randomUUID } from "node:crypto";
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
const MAX_UPSTREAM_BYTES = 2_000_000;

type ManagerRole = "viewer" | "manager" | "owner";
type ManagerAccess = { email: string; role: ManagerRole };

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

function managerAccess(request: NextRequest): ManagerAccess | null {
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

function auditActor(access: ManagerAccess): string | null {
  const key = process.env.BAR_AUDIT_HASH_KEY;
  if (!key) return null;
  return createHmac("sha256", key).update(access.email).digest("hex").slice(0, 24);
}

function auditRead(
  requestId: string,
  access: ManagerAccess,
  resource: string,
  status: number,
  startedAt: number,
) {
  const actor = auditActor(access);
  if (!actor) return;
  console.info(
    JSON.stringify({
      event: "manager_api_read",
      request_id: requestId,
      actor,
      role: access.role,
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

  const access = managerAccess(request);
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
      auditRead(requestId, access, resource, 502, startedAt);
      return json(
        "The local analytics service returned an invalid response.",
        502,
        requestId,
      );
    }

    const body = await readBoundedBody(upstream);
    auditRead(requestId, access, resource, upstream.status, startedAt);
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
    auditRead(requestId, access, resource, 502, startedAt);
    return json(
      "The local analytics service is temporarily unavailable.",
      502,
      requestId,
    );
  }
}
