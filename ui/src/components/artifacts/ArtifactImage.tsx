import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { getApiHeadersAsync } from "../../api/client.js";
import { BASE_URL } from "../../lib/config.js";

interface ArtifactImageProps {
  src?: string | null;
  alt: string;
  className?: string;
  style?: CSSProperties;
}

export function ArtifactImage({ src, alt, className, style }: ArtifactImageProps) {
  const authedPath = useMemo(() => toAuthedApiPath(src), [src]);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authedPath) return;
    let cancelled = false;
    let createdUrl: string | null = null;

    (async () => {
      try {
        const headers = await getApiHeadersAsync();
        const resp = await fetch(`${BASE_URL}${authedPath}`, { headers });
        if (!resp.ok) throw new Error(`image ${resp.status}`);
        const blob = await resp.blob();
        createdUrl = URL.createObjectURL(blob);
        if (!cancelled) {
          setObjectUrl(createdUrl);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "image failed");
      }
    })();

    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [authedPath]);

  if (!src) {
    return <ArtifactImageStatus text="no preview available" />;
  }
  if (!authedPath) {
    return <img src={src} alt={alt} className={className} style={style} loading="lazy" />;
  }
  if (error) {
    return <ArtifactImageStatus text={error} error />;
  }
  if (!objectUrl) {
    return <ArtifactImageStatus text="loading image..." />;
  }
  return <img src={objectUrl} alt={alt} className={className} style={style} />;
}

function ArtifactImageStatus({ text, error }: { text: string; error?: boolean }) {
  return (
    <div
      style={{
        padding: 14,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        color: error ? "var(--color-error)" : "var(--color-text-faint)",
      }}
    >
      {text}
    </div>
  );
}

function toAuthedApiPath(src?: string | null): string | null {
  if (!src || src.startsWith("data:") || src.startsWith("blob:")) return null;
  if (src.startsWith("/api/")) return src.slice(4);
  if (src.startsWith("/artifacts/")) return src;
  // Cast through `string` so the literal-type narrowing of BASE_URL
  // doesn't make this branch dead-on-type after the same-origin switch.
  const baseUrlStr: string = BASE_URL;
  if (baseUrlStr !== "/api" && src.startsWith(baseUrlStr)) {
    return src.slice(baseUrlStr.length) || "/";
  }
  try {
    const parsed = new URL(src, window.location.origin);
    if (parsed.origin === window.location.origin && parsed.pathname.startsWith("/api/")) {
      return parsed.pathname.slice(4) + parsed.search;
    }
  } catch {
    /* render as a normal image */
  }
  return null;
}
