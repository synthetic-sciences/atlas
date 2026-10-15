/** Pull a human-readable string out of anything thrown.
 *
 * Never returns "[object Object]" — falls back to JSON.stringify or
 * "Unknown error" when the value has no usable text field. */
export function errorMessage(e: unknown): string {
  const looksUseless = (s: unknown): boolean =>
    typeof s !== "string" || s === "" || s === "[object Object]";

  // Common Error shape (incl. ApiError which extends Error).
  if (e instanceof Error) {
    if (!looksUseless(e.message)) return e.message;
    // ApiError carries .detail too — try that before falling through.
    const det = (e as { detail?: unknown }).detail;
    if (typeof det === "string" && !looksUseless(det)) return det;
  }

  if (typeof e === "string" && !looksUseless(e)) return e;

  if (e && typeof e === "object") {
    const obj = e as Record<string, unknown>;
    for (const key of ["message", "detail", "error"] as const) {
      const v = obj[key];
      if (typeof v === "string" && !looksUseless(v)) return v;
      // Nested {detail: {message: "..."}} from FastAPI HTTPException(detail=dict).
      if (v && typeof v === "object") {
        const inner = (v as Record<string, unknown>).message;
        if (typeof inner === "string" && !looksUseless(inner)) return inner;
      }
    }
    try {
      const s = JSON.stringify(e);
      if (!looksUseless(s)) return s;
    } catch {
      /* circular ref — fall through */
    }
  }

  return "Unknown error";
}
