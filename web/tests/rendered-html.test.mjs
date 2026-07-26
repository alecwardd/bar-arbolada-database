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

test("server-renders the private manager dashboard shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Bar Arbolada Manager Analytics<\/title>/i);
  assert.match(html, /Executive Dashboard/);
  assert.match(html, /Private manager surface/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|react-loading-skeleton/i);
});

test("matches the existing Streamlit forest-and-coral theme", async () => {
  const [css, page, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(css, /--blue:\s*#2d6a4f/i);
  assert.match(css, /--coral:\s*#e76f51/i);
  assert.match(css, /--bg:\s*#f5f7f8/i);
  assert.match(css, /font-variant-numeric:\s*tabular-nums/i);
  assert.match(page, /ManagerDashboard/);
  assert.match(layout, /Bar Arbolada Manager Analytics/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
});
