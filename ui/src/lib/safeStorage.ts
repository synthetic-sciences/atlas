/**
 * Storage access that never throws.
 *
 * Chrome raises a SecurityError on the ``localStorage`` / ``sessionStorage``
 * property access itself when site data is blocked for the origin, and
 * Safari private mode rejects writes. A bare read inside a render or a
 * ``useState`` initializer would bubble into the ErrorBoundary and blank the
 * page, so every call site goes through these wrappers and degrades to the
 * same value an absent entry would produce.
 */

type StorageKind = "local" | "session";

function storageArea(kind: StorageKind): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    return kind === "session" ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}

function makeSafeStorage(kind: StorageKind) {
  return {
    getItem(key: string): string | null {
      try {
        return storageArea(kind)?.getItem(key) ?? null;
      } catch {
        return null;
      }
    },
    /** Returns ``true`` only when the write actually landed. */
    setItem(key: string, value: string): boolean {
      try {
        const area = storageArea(kind);
        if (!area) return false;
        area.setItem(key, value);
        return true;
      } catch {
        return false;
      }
    },
    removeItem(key: string): void {
      try {
        storageArea(kind)?.removeItem(key);
      } catch {
        // Nothing to remove when storage is unavailable.
      }
    },
  };
}

export const safeLocalStorage = makeSafeStorage("local");
export const safeSessionStorage = makeSafeStorage("session");

export const getItem = safeLocalStorage.getItem;
export const setItem = safeLocalStorage.setItem;
export const removeItem = safeLocalStorage.removeItem;
