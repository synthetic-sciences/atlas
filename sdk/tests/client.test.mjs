import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer } from "node:http";
import { AtlasClient, AtlasError } from "../index.mjs";

let server;
let baseUrl;
const seen = [];

before(async () => {
  server = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    seen.push({ path: request.url, method: request.method, headers: request.headers, body: Buffer.concat(chunks).toString() });
    response.setHeader("content-type", "application/json");
    if (request.url.endsWith("/missing")) {
      response.writeHead(404).end(JSON.stringify({ detail: "Node not found" }));
      return;
    }
    if (request.method === "DELETE") {
      response.writeHead(204).end();
      return;
    }
    response.end(JSON.stringify({ project_id: "project", ok: true }));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  baseUrl = `http://127.0.0.1:${server.address().port}/api/v1`;
});
after(() => new Promise(resolve => server.close(resolve)));

test("preserves the API prefix, request JSON, bearer, and idempotency key", async () => {
  const client = new AtlasClient({ baseUrl, token: async () => "test-token" });
  const project = await client.createProject({ title: "Research" }, { idempotencyKey: "create-once" });
  assert.equal(project.project_id, "project");
  const request = seen.at(-1);
  assert.equal(request.path, "/api/v1/projects");
  assert.equal(request.headers.authorization, "Bearer test-token");
  assert.equal(request.headers["idempotency-key"], "create-once");
  assert.deepEqual(JSON.parse(request.body), { title: "Research" });
});

test("encodes query values and node identifiers", async () => {
  const client = new AtlasClient({ baseUrl });
  await client.listNodes({ root_only: true, q: "a & b", ignored: undefined });
  const url = new URL(seen.at(-1).path, baseUrl);
  assert.equal(url.searchParams.get("q"), "a & b");
  assert.equal(url.searchParams.get("root_only"), "true");
  assert.equal(url.searchParams.has("ignored"), false);
  await client.getNode("node/one");
  assert.equal(seen.at(-1).path, "/api/v1/nodes/node%2Fone");
});

test("returns structured errors and handles empty responses", async () => {
  const client = new AtlasClient({ baseUrl });
  await assert.rejects(client.getNode("missing"), error => error instanceof AtlasError && error.status === 404 && error.message === "Node not found");
  assert.equal(await client.request("DELETE", "nodes/one"), undefined);
});

test("refuses credential-bearing URLs and paths escaping the API", async () => {
  assert.throws(() => new AtlasClient({ baseUrl: "https://token@example.test/api" }), TypeError);
  const client = new AtlasClient({ baseUrl, token: "private" });
  const count = seen.length;
  await assert.rejects(client.request("GET", "https://example.test/steal"), TypeError);
  await assert.rejects(client.request("GET", "../admin"), TypeError);
  assert.equal(seen.length, count);
});
