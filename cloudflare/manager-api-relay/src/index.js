const ALLOWED_PATHS = new Set([
  "/health",
  "/ready",
  "/api/v1/overview",
  "/api/v1/daily-sales",
  "/api/v1/staffing-rush",
  "/api/v1/profitability",
  "/api/v1/inventory/health",
  "/api/v1/import-operations",
]);

const CLIENT_ID_HEADER = "CF-Access-Client-Id";
const CLIENT_SECRET_HEADER = "CF-Access-Client-Secret";
const INTERNAL_ORIGIN = "http://manager-api.internal";
const ENCODER = new TextEncoder();

function response(message, status, extraHeaders = {}) {
  return Response.json(
    { message },
    {
      status,
      headers: {
        "cache-control": "private, no-store",
        "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
        "x-content-type-options": "nosniff",
        ...extraHeaders,
      },
    },
  );
}

async function secretsMatch(candidate, expected) {
  if (
    typeof candidate !== "string" ||
    typeof expected !== "string" ||
    candidate.length < 32 ||
    expected.length < 32
  ) {
    return false;
  }

  const [candidateHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", ENCODER.encode(candidate)),
    crypto.subtle.digest("SHA-256", ENCODER.encode(expected)),
  ]);
  const candidateBytes = new Uint8Array(candidateHash);
  const expectedBytes = new Uint8Array(expectedHash);
  let difference = candidateBytes.length ^ expectedBytes.length;
  for (let index = 0; index < candidateBytes.length; index += 1) {
    difference |= candidateBytes[index] ^ expectedBytes[index];
  }
  return difference === 0;
}

async function isAuthorized(request, env) {
  const [clientIdMatches, clientSecretMatches] = await Promise.all([
    secretsMatch(
      request.headers.get(CLIENT_ID_HEADER),
      env.RELAY_CLIENT_ID,
    ),
    secretsMatch(
      request.headers.get(CLIENT_SECRET_HEADER),
      env.RELAY_CLIENT_SECRET,
    ),
  ]);
  return clientIdMatches && clientSecretMatches;
}

function copyResponseHeaders(upstream) {
  const headers = new Headers({
    "cache-control": "private, no-store",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
  });
  for (const name of ["content-type", "x-request-id"]) {
    const value = upstream.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }
  return headers;
}

export async function handleRequest(request, env) {
  if (request.method !== "GET") {
    return response("Method not allowed.", 405, { allow: "GET" });
  }

  const url = new URL(request.url);
  if (!ALLOWED_PATHS.has(url.pathname)) {
    return response("Not found.", 404);
  }

  if (!(await isAuthorized(request, env))) {
    return response("Forbidden.", 403);
  }

  const authorization = request.headers.get("authorization");
  if (
    url.pathname.startsWith("/api/v1/") &&
    (!authorization || !authorization.startsWith("Bearer "))
  ) {
    return response("Forbidden.", 403);
  }

  const target = new URL(`${url.pathname}${url.search}`, INTERNAL_ORIGIN);
  const headers = new Headers({ accept: "application/json" });
  if (authorization) {
    headers.set("authorization", authorization);
  }

  try {
    const upstream = await env.MANAGER_API.fetch(
      new Request(target, {
        method: "GET",
        headers,
        redirect: "manual",
      }),
    );
    return new Response(upstream.body, {
      status: upstream.status,
      headers: copyResponseHeaders(upstream),
    });
  } catch {
    return response("Private analytics service unavailable.", 503);
  }
}

export default {
  fetch(request, env) {
    return handleRequest(request, env);
  },
};
