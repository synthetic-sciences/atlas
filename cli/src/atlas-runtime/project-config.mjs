// Per-project activation manifest (atlas.json).
//
// Shape:
//   {
//     "project_id": "able-helm-1359",
//     "auto": {
//       "enabled": true,
//       "log": true,
//       "web": "prefer_atlas"
//     }
//   }

import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

export const PROJECT_FILE = "atlas.json";

// Walk up from `startDir` to the filesystem root looking for atlas.json.
export async function findProjectConfig(startDir = process.cwd()) {
  let dir = path.resolve(startDir);
  for (;;) {
    const candidate = path.join(dir, PROJECT_FILE);
    try {
      const raw = await readFile(candidate, "utf8");
      return { path: candidate, config: JSON.parse(raw) };
    } catch {
      // not here (or unreadable / invalid JSON); keep walking up
    }
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

export function projectConfigProjectId(config) {
  const value = config && config.project_id;
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function projectAutoConfig(config) {
  const raw = config && typeof config.auto === "object" && !Array.isArray(config.auto) ? config.auto : {};
  return {
    enabled: raw.enabled !== false,
    log: raw.log !== false,
    web: raw.web || "prefer_atlas",
    capture: raw.capture || "suggest",
  };
}

export async function writeProjectConfig(dir = process.cwd(), extra = {}) {
  const target = path.join(path.resolve(dir), PROJECT_FILE);
  let existing = {};
  try {
    const parsed = JSON.parse(await readFile(target, "utf8"));
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) existing = parsed;
  } catch {
    existing = {};
  }
  const mergedAuto = {
    ...(existing.auto && typeof existing.auto === "object" && !Array.isArray(existing.auto) ? existing.auto : {}),
    ...(extra.auto && typeof extra.auto === "object" && !Array.isArray(extra.auto) ? extra.auto : {}),
  };
  const next = { ...existing, ...extra };
  // Scrub retired Library bindings when an older manifest is rewritten.
  delete next.source_ids;
  if (Object.keys(mergedAuto).length) next.auto = mergedAuto;
  await writeFile(target, `${JSON.stringify(next, null, 2)}\n`, "utf8");
  return { path: target, config: next };
}
