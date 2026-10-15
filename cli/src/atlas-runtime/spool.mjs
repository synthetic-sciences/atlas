// Flight Recorder client-side spool.
//
// When `atlas runs:record` can't reach the backend (laptop offline, fly
// hiccup, a 5xx from an upstream model), we don't want to lose the run
// — researchers don't re-run a 4-hour training job to recover a missed
// capture. So the CLI writes the failed payload to `~/.atlas/spool/`
// as a small JSON file and reports `{spooled: true, path: ...}`.
//
// On the next `atlas` invocation any local command flushes pending
// spool entries best-effort (the `flushSpool` helper). Successful posts
// delete the file; failures stay queued for next time.
//
// This is deliberately client-local. There is no daemon, no watcher,
// no background process — just files the next CLI run picks up.

import { mkdir, readdir, readFile, unlink, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";

export const SPOOL_DIR = path.join(homedir(), ".atlas", "spool");
// Permanently-failing entries (a malformed payload the backend rejects every
// time, e.g. an unresolved "<ROOT>" project_id) must not retry forever — one
// such entry was seen at 540 attempts, re-failing on every CLI invocation and
// poisoning `doctor`. After this many flush attempts we quarantine the entry
// here (preserved for inspection, never lost) and stop counting it as pending.
export const SPOOL_FAILED_DIR = path.join(SPOOL_DIR, "failed");
const MAX_FLUSH_ATTEMPTS = 50;

/**
 * Ensure the spool directory exists. Cheap: a `mkdir -p`.
 */
export async function ensureSpoolDir() {
  await mkdir(SPOOL_DIR, { recursive: true });
}

/**
 * Write a payload to the spool. Returns the absolute file path.
 *
 * Filename: `<epoch-ms>-<random>.json` so listing is naturally ordered
 * by creation time and parallel CLI invocations don't collide.
 */
export async function spoolPayload(route, body) {
  await ensureSpoolDir();
  const stamp = Date.now();
  const suffix = Math.random().toString(36).slice(2, 8);
  const file = path.join(SPOOL_DIR, `${stamp}-${suffix}.json`);
  const record = {
    route,
    body,
    spooled_at: new Date(stamp).toISOString(),
    attempts: 0,
    last_error: null,
    last_attempt_at: null,
  };
  await writeFile(file, JSON.stringify(record, null, 2), "utf8");
  return file;
}

/**
 * Cheap spool health summary for `atlas doctor`: how many entries are
 * queued, how old the oldest one is, and the last flush error seen.
 * The 0.7.3 outage hid behind "spooled successfully" for days — surfacing
 * age + the actual error makes a stuck spool diagnosable at a glance.
 */
export async function spoolStats() {
  const files = await listSpool();
  const stats = {
    pending: files.length,
    oldest_spooled_at: null,
    oldest_age_ms: null,
    last_error: null,
  };
  if (!files.length) return stats;
  for (const file of files) {
    try {
      const record = JSON.parse(await readFile(file, "utf8"));
      if (record.spooled_at && (stats.oldest_spooled_at === null || record.spooled_at < stats.oldest_spooled_at)) {
        stats.oldest_spooled_at = record.spooled_at;
      }
      if (record.last_error) stats.last_error = String(record.last_error).slice(0, 200);
    } catch {
      // Unparseable entry: count it, but don't fail the summary.
    }
  }
  if (stats.oldest_spooled_at) {
    const t = Date.parse(stats.oldest_spooled_at);
    if (Number.isFinite(t)) stats.oldest_age_ms = Math.max(0, Date.now() - t);
  }
  return stats;
}

/**
 * List queued spool entries, oldest first.
 */
export async function listSpool() {
  try {
    const files = await readdir(SPOOL_DIR);
    return files
      .filter((f) => f.endsWith(".json"))
      .sort()
      .map((f) => path.join(SPOOL_DIR, f));
  } catch (err) {
    if (err && err.code === "ENOENT") return [];
    throw err;
  }
}

/**
 * Replay spooled entries against `post(route, body)`. On success the
 * file is deleted; on failure it stays for the next flush so we never
 * lose a run by failing to retry it.
 *
 * Returns `{flushed: N, still_queued: M, errors: [...]}` so the caller
 * can log a short summary line. Errors are kept short — the goal is
 * "you have 3 runs still queued", not a stack trace.
 */
export async function flushSpool(post) {
  const files = await listSpool();
  let flushed = 0;
  let stillQueued = 0;
  let quarantined = 0;
  const errors = [];
  for (const file of files) {
    let record;
    try {
      record = JSON.parse(await readFile(file, "utf8"));
    } catch (err) {
      // Unparseable file - move on, leave it for the human to inspect.
      errors.push(`${path.basename(file)}: ${err && err.message}`);
      stillQueued += 1;
      continue;
    }
    // Migration: ``@synsci/atlas`` <= 0.7.2 wrote spool routes prefixed
    // with ``/api/v1`` because of a hard-coded path. The HTTP client now
    // expects routes relative to ``baseUrl`` (which already includes the
    // ``/api/v1`` prefix). Strip the leading ``/api/v1`` from any legacy
    // spool entry so we don't keep retrying it into a 404 forever.
    const route = String(record.route || "").replace(/^\/api\/v1(?=\/)/, "");
    try {
      await post(route, record.body);
      await unlink(file);
      flushed += 1;
    } catch (err) {
      const message = (err && err.message) || String(err);
      errors.push(`${path.basename(file)}: ${message}`);
      record.attempts = (Number(record.attempts) || 0) + 1;
      record.last_error = String(message).slice(0, 500);
      record.last_attempt_at = new Date().toISOString();
      if (record.attempts >= MAX_FLUSH_ATTEMPTS) {
        // Permanently stuck — quarantine so it stops retrying every invocation
        // and stops poisoning `doctor`. Preserved (never deleted) for inspection
        // or manual recovery from ~/.atlas/spool/failed/.
        try {
          await mkdir(SPOOL_FAILED_DIR, { recursive: true });
          await writeFile(
            path.join(SPOOL_FAILED_DIR, path.basename(file)),
            JSON.stringify(record, null, 2),
            "utf8",
          );
          await unlink(file);
          quarantined += 1;
        } catch {
          // If quarantine fails, leave the entry queued rather than lose it.
          stillQueued += 1;
        }
      } else {
        stillQueued += 1;
        // Record the failure on the entry itself so `run:spool:list` and
        // `doctor` can show *why* an entry is stuck, not just that it is.
        try {
          await writeFile(file, JSON.stringify(record, null, 2), "utf8");
        } catch {
          // Best-effort metadata; never let bookkeeping break the flush.
        }
      }
    }
  }
  return { flushed, still_queued: stillQueued, quarantined, errors };
}
