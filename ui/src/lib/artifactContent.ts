import { BASE_URL } from "./config";
import { getAuthHeaders } from "../api/internal";

/**
 * Resolve the textual body of an artifact.
 *
 * Large artifacts keep their bytes in object storage, not inline, so
 * `metadata.content` may be null. This fetches
 * is why the viewer used to show "no text content available." This fetches the
 * real bytes: first via the ACL-checked backend download route (works in dev +
 * prod), then any absolute signed `storage_url` as a fallback. Returns null if
 * the body can't be retrieved.
 */
export async function fetchArtifactText(
  a: {
    metadata?: Record<string, unknown> | null;
    storage_path?: string | null;
    storage_url?: string | null;
  },
): Promise<string | null> {
  const inline = a.metadata?.content;
  if (typeof inline === "string" && inline.length > 0) return inline;

  const get = async (url: string, withAuth: boolean): Promise<string | null> => {
    try {
      const headers = withAuth ? await getAuthHeaders() : undefined;
      const res = await fetch(url, headers ? { headers } : undefined);
      return res.ok ? await res.text() : null;
    } catch {
      return null;
    }
  };

  // Canonical blob URL. It may be a same-origin authenticated URL or an
  // absolute signed URL.
  const url = a.storage_url;
  if (url) {
    const relative = url.startsWith("/");
    const txt = await get(url, relative);
    if (txt != null) return txt;
  }

  // Fallback for artifacts keyed by a *relative* storage path
  // (GET /api/artifacts/download/{path:path}).
  const sp = a.storage_path;
  if (sp && !sp.startsWith("/")) {
    const encoded = sp.split("/").map(encodeURIComponent).join("/");
    const txt = await get(`${BASE_URL}/artifacts/download/${encoded}`, true);
    if (txt != null) return txt;
  }
  return null;
}

/**
 * Open an artifact in a new tab or download it. The blob route requires an
 * Authorization header, so a raw <a href> navigation fails with "Missing
 * Authorization header" — fetch the bytes with auth and hand the browser an
 * object URL instead. Absolute signed URLs are fetched without auth. For
 * "open" the tab is grabbed synchronously to survive popup blockers.
 */
export async function openOrDownloadArtifact(
  storageUrl: string | null | undefined,
  filename: string,
  mode: "open" | "download",
): Promise<void> {
  if (!storageUrl) return;
  const absolute = /^https?:\/\//.test(storageUrl);
  let win: Window | null = null;
  if (mode === "open") win = window.open("", "_blank");
  try {
    const headers = absolute ? undefined : await getAuthHeaders();
    const resp = await fetch(storageUrl, headers ? { headers } : undefined);
    if (!resp.ok) throw new Error(`http ${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    if (mode === "open") {
      if (win) win.location.href = url;
      else window.open(url, "_blank");
    } else {
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || "download";
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch {
    if (win) win.close();
  }
}
