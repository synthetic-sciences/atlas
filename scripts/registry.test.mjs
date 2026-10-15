import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";
import { waitForPackage } from "./registry.mjs";

async function registry(t, respond) {
  const server = http.createServer(respond);
  server.listen(0, "127.0.0.1");
  await new Promise(resolve => server.once("listening", resolve));
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  return `http://127.0.0.1:${server.address().port}`;
}

test("waits through registry processing and validates the published artifact", async t => {
  let calls = 0;
  const url = await registry(t, (req, res) => {
    assert.equal(req.url, "/%40synsci%2Fatlas/0.16.0");
    res.writeHead(++calls < 3 ? 404 : 200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ dist: { integrity: "sha512-expected" } }));
  });
  await waitForPackage("@synsci/atlas", "0.16.0", "sha512-expected", { registry: url, intervalMs: 1, timeoutMs: 1000 });
  assert.equal(calls, 3);
});

test("refuses a different published artifact immediately", async t => {
  const url = await registry(t, (_req, res) => res.end(JSON.stringify({ dist: { integrity: "sha512-other" } })));
  await assert.rejects(waitForPackage("pkg", "1.0.0", "sha512-expected", { registry: url }), /integrity differs/);
});

test("does not retry an authorization failure", async t => {
  let calls = 0;
  const url = await registry(t, (_req, res) => { calls++; res.writeHead(403); res.end(); });
  await assert.rejects(waitForPackage("pkg", "1.0.0", "expected", { registry: url }), /HTTP 403/);
  assert.equal(calls, 1);
});

test("bounds the wait when a package stays unavailable", async t => {
  const url = await registry(t, (_req, res) => { res.writeHead(404); res.end(); });
  await assert.rejects(waitForPackage("pkg", "1.0.0", "expected", { registry: url, intervalMs: 1, timeoutMs: 25 }), /deadline/);
});
