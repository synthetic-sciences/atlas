import { useEffect, useState } from "react";
import { Modal } from "./Modal";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { FONT_MONO as mono, FONT_SANS as sans } from "../../styles/tokens";
import { fetchArtifactText, openOrDownloadArtifact } from "../../lib/artifactContent";
import { getAuthHeaders } from "../../api/internal";

/**
 * FilePreviewModal — a proper in-app file viewer.
 *
 * Replaces the "open in new tab" flow (which hit the auth-protected blob route
 * with no Authorization header). Fetches the bytes with auth and renders them
 * inline by type: markdown rendered, JSON / JSONL pretty-printed, CSV/TSV as a
 * table, text/log/code monospaced, images inline. Anything else offers a
 * download. Works for any artifact/asset that exposes a ``storageUrl``.
 */

export interface PreviewItem {
  title: string;
  mime?: string | null;
  storageUrl?: string | null;
  storagePath?: string | null;
  metadata?: Record<string, unknown> | null;
  sizeBytes?: number | null;
}

type Kind = "markdown" | "json" | "jsonl" | "csv" | "tsv" | "image" | "text" | "binary";

function classify(item: PreviewItem): Kind {
  const name = (item.title || "").toLowerCase();
  const mime = (item.mime || "").toLowerCase();
  if (mime.startsWith("image/") || /\.(png|jpe?g|gif|webp|svg|avif|bmp)$/.test(name)) return "image";
  if (mime === "text/markdown" || /\.(md|markdown|rst)$/.test(name)) return "markdown";
  if (/\.(jsonl|ndjson)$/.test(name)) return "jsonl";
  if (mime === "application/json" || mime.endsWith("+json") || /\.json$/.test(name)) return "json";
  if (mime === "text/csv" || /\.csv$/.test(name)) return "csv";
  if (mime === "text/tab-separated-values" || /\.tsv$/.test(name)) return "tsv";
  if (
    mime.startsWith("text/") ||
    /\.(txt|log|ya?ml|toml|ini|cfg|env|py|js|ts|tsx|jsx|sh|bash|c|cpp|h|hpp|java|go|rs|rb|sql|html?|xml|css)$/.test(name)
  )
    return "text";
  return "binary";
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function FilePreviewModal({
  item,
  open,
  onClose,
}: {
  item: PreviewItem | null;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Modal open={open && !!item} onClose={onClose} title={item?.title} maxWidth={880}>
      {item && <PreviewToolbar item={item} />}
      {item && <PreviewBody item={item} />}
    </Modal>
  );
}

function PreviewToolbar({ item }: { item: PreviewItem }) {
  const kind = classify(item);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 16px",
        borderBottom: "1px solid var(--color-border)",
        fontFamily: mono,
        fontSize: 10.5,
        color: "var(--color-text-faint)",
      }}
    >
      <span style={{ letterSpacing: "0.06em" }}>{kind}</span>
      {item.mime && <span>· {item.mime}</span>}
      {item.sizeBytes != null && <span>· {formatBytes(item.sizeBytes)}</span>}
      <span style={{ flex: 1 }} />
      <button
        type="button"
        onClick={() => openOrDownloadArtifact(item.storageUrl, item.title, "download")}
        style={{
          all: "unset",
          cursor: "pointer",
          color: "var(--color-text-muted)",
          fontFamily: mono,
          fontSize: 10.5,
        }}
        title="Download"
      >
        download ↓
      </button>
    </div>
  );
}

function PreviewBody({ item }: { item: PreviewItem }) {
  const kind = classify(item);
  if (kind === "image") return <ImagePreview item={item} />;
  if (kind === "binary") {
    return (
      <Status muted>
        {(item.mime || "binary")} · no inline preview — use download.
      </Status>
    );
  }
  return <TextPreview item={item} kind={kind} />;
}

function useText(item: PreviewItem) {
  const [state, setState] = useState<{ loading: boolean; text?: string; error?: boolean }>({
    loading: true,
  });
  useEffect(() => {
    let alive = true;
    setState({ loading: true });
    fetchArtifactText({
      metadata: item.metadata ?? null,
      storage_path: item.storagePath ?? null,
      storage_url: item.storageUrl ?? null,
    }).then((t) => {
      if (!alive) return;
      setState(t == null ? { loading: false, error: true } : { loading: false, text: t });
    });
    return () => {
      alive = false;
    };
  }, [item.storageUrl, item.storagePath]);
  return state;
}

function TextPreview({ item, kind }: { item: PreviewItem; kind: Kind }) {
  const { loading, text, error } = useText(item);
  if (loading) return <Status>loading…</Status>;
  if (error || text == null) return <Status error>couldn't load file contents.</Status>;

  if (kind === "markdown") {
    return (
      <div style={{ padding: "16px 20px", fontFamily: sans, fontSize: 13.5, lineHeight: 1.6 }}>
        <MarkdownRenderer content={text} />
      </div>
    );
  }

  if (kind === "csv" || kind === "tsv") {
    return <CsvTable text={text} delim={kind === "csv" ? "," : "\t"} />;
  }

  let body = text;
  if (kind === "json") {
    try {
      body = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      /* leave raw */
    }
  } else if (kind === "jsonl") {
    body = text
      .split(/\r?\n/)
      .filter((l) => l.trim().length > 0)
      .map((l) => {
        try {
          return JSON.stringify(JSON.parse(l), null, 2);
        } catch {
          return l;
        }
      })
      .join("\n\n");
  }

  return (
    <pre
      style={{
        margin: 0,
        padding: "16px 20px",
        fontFamily: mono,
        fontSize: 12,
        lineHeight: 1.6,
        color: "var(--color-text)",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {body}
    </pre>
  );
}

function CsvTable({ text, delim }: { text: string; delim: string }) {
  const rows = text
    .split(/\r?\n/)
    .filter((l) => l.length > 0)
    .map((l) => l.split(delim));
  if (rows.length === 0) return <Status muted>empty</Status>;
  const [head, ...body] = rows;
  return (
    <div className="data-table-shell" style={{ overflow: "auto" }}>
      <table className="data-table">
        <thead>
          <tr>
            {head.map((c, i) => (
              <th
                key={i}
                style={{
                  textAlign: "left",
                }}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri}>
              {row.map((c, ci) => (
                <td
                  key={ci}
                  style={{
                    whiteSpace: "nowrap",
                  }}
                >
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ImagePreview({ item }: { item: PreviewItem }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let alive = true;
    let obj: string | null = null;
    const src = item.storageUrl;
    if (!src) {
      setError(true);
      return;
    }
    (async () => {
      try {
        const absolute = /^https?:\/\//.test(src);
        const headers = absolute ? undefined : await getAuthHeaders();
        const resp = await fetch(src, headers ? { headers } : undefined);
        if (!resp.ok) throw new Error();
        obj = URL.createObjectURL(await resp.blob());
        if (alive) setUrl(obj);
      } catch {
        if (alive) setError(true);
      }
    })();
    return () => {
      alive = false;
      if (obj) URL.revokeObjectURL(obj);
    };
  }, [item.storageUrl]);

  if (error) return <Status error>couldn't load image.</Status>;
  if (!url) return <Status>loading image…</Status>;
  return (
    <div style={{ padding: 16, display: "flex", justifyContent: "center", background: "var(--color-bg-subtle)" }}>
      <img src={url} alt={item.title} style={{ maxWidth: "100%", maxHeight: "70vh", objectFit: "contain" }} />
    </div>
  );
}

function Status({ children, error, muted }: { children: React.ReactNode; error?: boolean; muted?: boolean }) {
  return (
    <div
      style={{
        padding: "28px 20px",
        textAlign: "center",
        fontFamily: mono,
        fontSize: 11,
        color: error ? "var(--color-error)" : muted ? "var(--color-text-muted)" : "var(--color-text-faint)",
      }}
    >
      {children}
    </div>
  );
}
