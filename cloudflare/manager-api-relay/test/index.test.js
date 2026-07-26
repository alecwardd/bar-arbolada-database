import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import test from "node:test";

import { handleRequest } from "../src/index.js";

if (!globalThis.crypto) {
  globalThis.crypto = webcrypto;
}

const CLIENT_ID = "manager-relay-client-id-that-is-long-enough";
const CLIENT_SECRET = "manager-relay-client-secret-that-is-long-enough";
const API_TOKEN = "manager-api-token-that-is-long-enough";

function request(path, options = {}) {
  const headers = new Headers(options.headers);
  headers.set("CF-Access-Client-Id", CLIENT_ID);
  headers.set("CF-Access-Client-Secret", CLIENT_SECRET);
  return new Request(`https://relay.example${path}`, {
    ...options,
    headers,
  });
}

function environment(fetchImpl) {
  return {
    RELAY_CLIENT_ID: CLIENT_ID,
    RELAY_CLIENT_SECRET: CLIENT_SECRET,
    MANAGER_API: { fetch: fetchImpl },
  };
}

test("rejects missing relay credentials without reaching the origin", async () => {
  const response = await handleRequest(
    new Request("https://relay.example/health"),
    environment(() => {
      throw new Error("origin must not be reached");
    }),
  );

  assert.equal(response.status, 403);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
});

test("rejects paths and methods outside the narrow allowlist", async () => {
  const env = environment(() => {
    throw new Error("origin must not be reached");
  });

  assert.equal((await handleRequest(request("/admin"), env)).status, 404);
  assert.equal(
    (
      await handleRequest(
        request("/api/v1/overview", { method: "POST" }),
        env,
      )
    ).status,
    405,
  );
});

test("requires the local API bearer token for analytics reads", async () => {
  const response = await handleRequest(
    request("/api/v1/overview"),
    environment(() => {
      throw new Error("origin must not be reached");
    }),
  );

  assert.equal(response.status, 403);
});

test("forwards an allowed read to the fixed private service", async () => {
  let forwarded;
  const env = environment(async (upstream) => {
    forwarded = upstream;
    return Response.json(
      { status: "ok" },
      {
        headers: {
          "cache-control": "public, max-age=3600",
          "set-cookie": "must-not-leak=true",
          "x-request-id": "request-123",
        },
      },
    );
  });
  const response = await handleRequest(
    request("/api/v1/overview?preset=week", {
      headers: { authorization: `Bearer ${API_TOKEN}` },
    }),
    env,
  );

  assert.equal(forwarded.url, "http://manager-api.internal/api/v1/overview?preset=week");
  assert.equal(forwarded.method, "GET");
  assert.equal(forwarded.headers.get("authorization"), `Bearer ${API_TOKEN}`);
  assert.equal(forwarded.headers.get("CF-Access-Client-Secret"), null);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("x-request-id"), "request-123");
});

test("returns a minimal unavailable response when the VPC binding fails", async () => {
  const response = await handleRequest(
    request("/health"),
    environment(() => {
      throw new Error("private network details");
    }),
  );

  assert.equal(response.status, 503);
  assert.doesNotMatch(await response.text(), /private network details/);
});
