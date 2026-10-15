import assert from "node:assert/strict";
import { setTimeout } from "node:timers/promises";

export async function waitForPackage(name, version, integrity, options = {}) {
  const registry = options.registry ?? "https://registry.npmjs.org";
  const deadline = Date.now() + (options.timeoutMs ?? 300_000);
  const interval = options.intervalMs ?? 5_000;
  const url = `${registry}/${encodeURIComponent(name)}/${encodeURIComponent(version)}`;
  while (Date.now() < deadline) {
    const response = await fetch(url, { signal: AbortSignal.timeout(10_000), headers: { "Cache-Control": "no-cache" } }).catch(() => undefined);
    if (response?.ok) {
      const published = await response.json();
      assert.equal(published.dist?.integrity, integrity, `Published integrity differs for ${name}@${version}`);
      return;
    }
    if (response && ![404, 408, 425, 429].includes(response.status) && response.status < 500) {
      throw new Error(`Registry verification rejected ${name}@${version}: HTTP ${response.status}`);
    }
    await setTimeout(Math.min(interval, Math.max(0, deadline - Date.now())));
  }
  throw new Error(`Registry processing did not complete for ${name}@${version} before the verification deadline`);
}
