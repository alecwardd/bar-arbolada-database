import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${path}`, {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the private partner dashboard shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Bar Arbolada Partner Analytics<\/title>/i);
  assert.match(html, /Private · Read-only/);
  assert.match(html, /A private, read-only operating pulse/);
  assert.match(html, /Send feedback/);
  assert.doesNotMatch(html, /How the room is running/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|react-loading-skeleton/i);
});

test("matches the Warm Venue Editorial forest-and-coral theme", async () => {
  const [css, page, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(css, /--forest:\s*#2d6a4f/i);
  assert.match(css, /--coral:\s*#e76f51/i);
  assert.match(css, /--bg:\s*#f3f1eb/i);
  assert.match(css, /font-variant-numeric:\s*tabular-nums/i);
  assert.match(page, /ManagerDashboard/);
  assert.match(layout, /Bar Arbolada Partner Analytics/);
  assert.match(layout, /Geist/);
  assert.doesNotMatch(layout, /Fraunces|Manrope/);
  assert.match(packageJson, /plotly\.js-basic-dist-min/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
});

test("manager proxy fails closed with role-aware pseudonymous auditing", async () => {
  const route = await readFile(
    new URL("../app/api/manager/[...path]/route.ts", import.meta.url),
    "utf8",
  );
  const access = await readFile(
    new URL("../app/lib/manager-access.ts", import.meta.url),
    "utf8",
  );
  const feedback = await readFile(
    new URL("../app/api/feedback/route.ts", import.meta.url),
    "utf8",
  );

  assert.match(access, /BAR_MANAGER_ROLES/);
  assert.match(route, /BAR_AUDIT_HASH_KEY/);
  assert.match(route, /createHmac\("sha256"/);
  assert.match(route, /MAX_UPSTREAM_BYTES/);
  assert.match(route, /CF_ACCESS_CLIENT_ID/);
  assert.match(route, /CF_ACCESS_CLIENT_SECRET/);
  assert.match(route, /manager_api_read/);
  assert.match(feedback, /RESEND_API_KEY/);
  assert.match(feedback, /FEEDBACK_TO_EMAIL/);
  assert.doesNotMatch(route, /console\.(?:info|log|warn|error)\([^)]*access\.email/);
  assert.doesNotMatch(feedback, /console\.(?:info|log|warn|error)\([^)]*access\.email/);
});
