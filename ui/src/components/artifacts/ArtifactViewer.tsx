import { useState, useMemo, useEffect } from "react";
import type { Artifact } from "../../api/types.js";
import { ArtifactImage } from "./ArtifactImage.js";
import { fetchArtifactText, openOrDownloadArtifact } from "../../lib/artifactContent.js";

// Artifact types whose viewer renders a textual body. For these we fetch the
// stored bytes when no inline content is present (sandbox-produced artifacts
// keep their bytes in storage, not inline).
const TEXTUAL_TYPES = new Set([
  "text",
  "table",
  "json",
  "html",
  "plotly_html",
  "vega",
  "diff_carousel",
]);

// Files whose extension is plainly text even when mime-guessing typed them
// "binary" (e.g. .jsonl logs, transcripts). We still fetch + show these.
const TEXTUAL_EXT = /\.(md|txt|log|jsonl|ndjson|csv|tsv|json|ya?ml|html?)$/i;

function isTextual(artifact: Artifact): boolean {
  if (TEXTUAL_TYPES.has(artifact.artifact_type)) return true;
  return TEXTUAL_EXT.test(artifact.title || artifact.filename || "");
}

/** Resolve an artifact's textual body: inline content if present, else the
 *  stored bytes fetched on demand. */
function useResolvedContent(artifact: Artifact): {
  content: string | undefined;
  loading: boolean;
} {
  const inline = artifact.metadata?.content as string | undefined;
  const [content, setContent] = useState<string | undefined>(
    typeof inline === "string" && inline.length > 0 ? inline : undefined,
  );
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (typeof inline === "string" && inline.length > 0) {
      setContent(inline);
      return;
    }
    if (!isTextual(artifact)) return;
    let alive = true;
    setLoading(true);
    fetchArtifactText(artifact).then((t) => {
      if (!alive) return;
      setContent(t ?? undefined);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifact.artifact_id]);

  return { content, loading };
}

interface ArtifactViewerProps {
  artifact: Artifact;
}

/* ------------------------------------------------------------------ */
/*  JSON tree with collapsible sections                                */
/* ------------------------------------------------------------------ */

function JsonNode({ data, depth = 0 }: { data: unknown; depth?: number }) {
  const [collapsed, setCollapsed] = useState(depth > 2);

  if (data === null) return <span className="text-[var(--color-text-faint)]">null</span>;
  if (typeof data === "boolean")
    return <span className="text-[var(--color-accent)]">{String(data)}</span>;
  if (typeof data === "number")
    return <span className="text-[var(--color-accent)]">{data}</span>;
  if (typeof data === "string")
    return <span className="text-green-500">"{data}"</span>;

  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="text-[var(--color-text-muted)]">[]</span>;
    return (
      <span>
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="mr-1 text-[var(--color-text-faint)] hover:text-[var(--color-text)] focus:outline-none"
        >
          {collapsed ? "+" : "-"}
        </button>
        {"["}
        {collapsed ? (
          <span className="text-[var(--color-text-faint)]"> {data.length} items... </span>
        ) : (
          <div className="ml-4">
            {data.map((item, i) => (
              <div key={i}>
                <JsonNode data={item} depth={depth + 1} />
                {i < data.length - 1 && ","}
              </div>
            ))}
          </div>
        )}
        {"]"}
      </span>
    );
  }

  if (typeof data === "object") {
    const entries = Object.entries(data as Record<string, unknown>);
    if (entries.length === 0)
      return <span className="text-[var(--color-text-muted)]">{"{}"}</span>;
    return (
      <span>
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="mr-1 text-[var(--color-text-faint)] hover:text-[var(--color-text)] focus:outline-none"
        >
          {collapsed ? "+" : "-"}
        </button>
        {"{"}
        {collapsed ? (
          <span className="text-[var(--color-text-faint)]"> {entries.length} keys... </span>
        ) : (
          <div className="ml-4">
            {entries.map(([key, val], i) => (
              <div key={key}>
                <span className="text-[var(--color-text-muted)]">"{key}"</span>:{" "}
                <JsonNode data={val} depth={depth + 1} />
                {i < entries.length - 1 && ","}
              </div>
            ))}
          </div>
        )}
        {"}"}
      </span>
    );
  }

  return <span>{String(data)}</span>;
}

/* ------------------------------------------------------------------ */
/*  CSV table renderer                                                 */
/* ------------------------------------------------------------------ */

function CsvTable({ content }: { content: string }) {
  const rows = content
    .trim()
    .split("\n")
    .map((row) => row.split(",").map((cell) => cell.trim()));

  if (rows.length === 0) return <p className="text-[var(--color-text-muted)]">empty table</p>;

  const [header, ...body] = rows;

  return (
    <div className="data-table-shell">
      <table className="data-table">
        <thead>
          <tr className="border-b border-[var(--color-border)] bg-[var(--color-bg-elevated)]">
            {header.map((cell, i) => (
              <th
                key={i}
                className="px-3 py-2 font-medium text-[var(--color-text)]"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr
              key={ri}
              className="border-b border-[var(--color-border)] last:border-0"
            >
              {row.map((cell, ci) => (
                <td key={ci} className="px-3 py-2 text-[var(--color-text-muted)]">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  File info card (for checkpoint / binary)                           */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/*  Vega spec viewer                                                   */
/* ------------------------------------------------------------------ */

function VegaViewer({ content }: { content: string | undefined }) {
  const spec = content ?? "{}";

  const [showSpec, setShowSpec] = useState(false);

  let parsed: unknown = null;
  try {
    parsed = JSON.parse(spec);
  } catch {
    parsed = null;
  }

  // Build an inline HTML document that loads vega-embed from CDN and renders the spec.
  // The spec is serialized as escaped JSON, not interpolated as raw script.
  const iframeSrcDoc = useMemo(() => {
    const serializedSpec = JSON.stringify(parsed).replace(/</g, "\\u003c");
    return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    /* The artifact iframe is a sandboxed document so it can't read the
       outer app's CSS variables; mirror the design-system tokens inline
       and switch on prefers-color-scheme so dark-mode users don't get a
       flashbang. Token values are kept in sync with styles/index.css. */
    body { margin: 0; padding: 16px; background: #fafbfc; color: #0f172a; font-family: 'Computer Modern Serif', 'Latin Modern Roman', Georgia, 'Times New Roman', serif; display: flex; justify-content: center; align-items: flex-start; }
    #vis { width: 100%; }
    .vega-embed { width: 100%; }
    .vega-embed .chart-wrapper { width: 100%; }
    .error { color: #b91c1c; padding: 16px; font-size: 13px; font-family: 'JetBrains Mono', 'SF Mono', ui-monospace, monospace; }
    @media (prefers-color-scheme: dark) {
      body { background: #0c0c0d; color: #fafafa; }
      .error { color: #ef4444; }
    }
  </style>
</head>
<body>
  <div id="vis"></div>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
  <script>
    function renderError(prefix, err) {
      var el = document.getElementById('vis');
      el.className = 'error';
      el.textContent = prefix + ': ' + (err && err.message ? err.message : String(err || 'unknown error'));
    }
    try {
      var spec = ${serializedSpec};
      if (!spec || typeof spec !== 'object' || Array.isArray(spec)) {
        throw new Error('spec must be a valid JSON object');
      }
      vegaEmbed('#vis', spec, { actions: false, renderer: 'svg' })
        .catch(function(err) { renderError('render error', err); });
    } catch(e) {
      renderError('invalid spec', e);
    }
  </script>
</body>
</html>`;
  }, [parsed]);

  return (
    <div className="space-y-3">
      {/* Header bar */}
      <div
        className="flex items-center justify-between rounded-sm border border-[var(--color-border)] bg-[var(--color-bg-elevated)] px-4 py-3"
      >
        <div className="flex items-center gap-2">
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-[var(--color-accent)]"
          >
            <path d="M1 14 4 4l3 6 2-3 3 7M14 2l-3 4" />
          </svg>
          <span
            style={{
              fontFamily: "'Computer Modern', 'Latin Modern Roman', Georgia, 'Times New Roman', serif",
              fontSize: "13px",
              fontWeight: 500,
              color: "var(--color-text)",
            }}
          >
            vega visualization
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSpec((v) => !v)}
            className="rounded px-2.5 py-1 text-xs transition-opacity hover:opacity-80"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "10px",
              fontWeight: 500,
              color: "var(--color-text-muted)",
              backgroundColor: "var(--color-bg)",
              border: "1px solid var(--color-border)",
            }}
          >
            {showSpec ? "hide spec" : "view spec"}
          </button>
          <button
            onClick={() => {
              navigator.clipboard.writeText(spec);
            }}
            className="rounded px-2.5 py-1 text-xs transition-opacity hover:opacity-80"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "10px",
              fontWeight: 500,
              color: "var(--color-text-muted)",
              backgroundColor: "var(--color-bg)",
              border: "1px solid var(--color-border)",
            }}
          >
            copy spec
          </button>
          <a
            href="https://vega.github.io/editor/"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded px-2.5 py-1 text-xs transition-opacity hover:opacity-80"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "10px",
              fontWeight: 500,
              color: "var(--color-accent)",
              backgroundColor: "var(--color-bg)",
              border: "1px solid var(--color-border)",
              textDecoration: "none",
            }}
          >
            open in vega editor
          </a>
        </div>
      </div>

      {/* Live Vega render via sandboxed iframe */}
      <iframe
        srcDoc={iframeSrcDoc}
        sandbox="allow-scripts"
        title="vega visualization"
        className="w-full rounded-sm border border-[var(--color-border)]"
        style={{ height: "400px", background: "var(--color-bg)" }}
      />

      {/* Collapsible JSON spec preview */}
      {showSpec && (
        <div className="overflow-x-auto rounded-sm border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-4 font-mono text-sm leading-relaxed text-[var(--color-text)]"
          style={{ maxHeight: 320, overflowY: "auto" }}
        >
          <JsonNode data={parsed} />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Diff carousel viewer                                               */
/* ------------------------------------------------------------------ */

function DiffCarouselViewer({ content }: { content: string | undefined }) {
  const [activeTab, setActiveTab] = useState(0);

  const items: unknown[] = useMemo(() => {
    if (!content) return [];
    try {
      const parsed = JSON.parse(content);
      if (Array.isArray(parsed)) return parsed;
      if (
        typeof parsed === "object" &&
        parsed !== null &&
        "items" in parsed &&
        Array.isArray((parsed as Record<string, unknown>).items)
      ) {
        return (parsed as Record<string, unknown>).items as unknown[];
      }
      // Single object - wrap in array
      return [parsed];
    } catch {
      // Not JSON - treat as plain text
      return [content];
    }
  }, [content]);

  if (items.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-sm border border-dashed border-[var(--color-border)] bg-[var(--color-bg-elevated)]">
        <p className="text-sm text-[var(--color-text-faint)]">
          no diff items available.
        </p>
      </div>
    );
  }

  // Side-by-side if exactly 2 items
  if (items.length === 2) {
    return (
      <div className="grid grid-cols-2 gap-3">
        {items.map((item, i) => (
          <div
            key={i}
            className="overflow-x-auto rounded-sm border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-4"
          >
            <p
              className="mb-2"
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: "9px",
                fontWeight: 600,
                letterSpacing: "0.08em",
                color: i === 0 ? "var(--color-error)" : "var(--color-success)",
              }}
            >
              {i === 0 ? "before" : "after"}
            </p>
            <div
              className="font-mono text-sm leading-relaxed text-[var(--color-text)]"
              style={{ maxHeight: 300, overflowY: "auto" }}
            >
              {typeof item === "string" ? (
                <pre className="whitespace-pre-wrap">{item}</pre>
              ) : (
                <JsonNode data={item} />
              )}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // Tabbed view for 3+ items
  return (
    <div className="space-y-2">
      {/* Tab bar */}
      <div
        className="flex gap-1 overflow-x-auto rounded-sm border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-1"
      >
        {items.map((_, i) => (
          <button
            key={i}
            onClick={() => setActiveTab(i)}
            className="shrink-0 rounded px-3 py-1.5 transition-colors"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "10px",
              fontWeight: activeTab === i ? 600 : 400,
              backgroundColor:
                activeTab === i
                  ? "var(--color-accent-subtle, rgba(99, 130, 255, 0.1))"
                  : "transparent",
              color:
                activeTab === i
                  ? "var(--color-accent)"
                  : "var(--color-text-faint)",
            }}
          >
            item {i + 1}
          </button>
        ))}
      </div>

      {/* Active item */}
      <div
        className="overflow-x-auto rounded-sm border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-4 font-mono text-sm leading-relaxed text-[var(--color-text)]"
        style={{ maxHeight: 400, overflowY: "auto" }}
      >
        {typeof items[activeTab] === "string" ? (
          <pre className="whitespace-pre-wrap">
            {items[activeTab] as string}
          </pre>
        ) : (
          <JsonNode data={items[activeTab]} />
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  File info card (for checkpoint / binary)                           */
/* ------------------------------------------------------------------ */

function FileInfoCard({ artifact }: { artifact: Artifact }) {
  // payload is `unknown` on the wire; narrow before reading media_type.
  const mediaType =
    artifact.payload && typeof artifact.payload === "object"
      ? (artifact.payload as Record<string, unknown>).media_type
      : undefined;
  return (
    <div className="rounded-sm border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-sm bg-[var(--color-accent-subtle)]">
          <svg
            width="20"
            height="20"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-[var(--color-accent)]"
          >
            <path d="M4 3h8l4 4v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
            <path d="M12 3v4h4" />
          </svg>
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-[var(--color-text)]">
            {artifact.title}
          </p>
          <p className="text-xs text-[var(--color-text-faint)]">
            {(typeof mediaType === "string" ? mediaType : null) ?? artifact.artifact_type} &middot;{" "}
            {artifact.storage_path}
          </p>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main ArtifactViewer                                                */
/* ------------------------------------------------------------------ */

export function ArtifactViewer({ artifact }: ArtifactViewerProps) {
  const { content, loading } = useResolvedContent(artifact);

  function renderByType() {
    switch (artifact.artifact_type) {
      case "text":
        return (
          <pre className="whitespace-pre-wrap rounded-sm border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-4 text-sm leading-relaxed text-[var(--color-text)]">
            {content ?? (loading ? "loading…" : "no text content available.")}
          </pre>
        );

      case "table":
        return content ? (
          <CsvTable content={content} />
        ) : (
          <p className="text-sm text-[var(--color-text-muted)]">no table data available.</p>
        );

      case "json": {
        let parsed: unknown = null;
        try {
          parsed = JSON.parse(content ?? "{}");
        } catch {
          parsed = content;
        }
        return (
          <div className="overflow-x-auto rounded-sm border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-4 font-mono text-sm leading-relaxed text-[var(--color-text)]">
            <JsonNode data={parsed} />
          </div>
        );
      }

      case "image":
        return (
          <div className="overflow-hidden rounded-sm border border-[var(--color-border)]">
            <ArtifactImage
              src={artifact.storage_url ?? artifact.storage_path}
              alt={artifact.title}
              className="max-h-[600px] w-full object-contain"
            />
          </div>
        );

      case "banner":
        return (
          <div className="w-full overflow-hidden rounded-sm border border-[var(--color-border)]">
            <ArtifactImage
              src={artifact.storage_url ?? artifact.storage_path}
              alt={artifact.title}
              className="h-auto w-full object-cover"
            />
          </div>
        );

      case "html":
        return (
          <iframe
            srcDoc={content ?? ""}
            sandbox="allow-scripts"
            title={artifact.title}
            className="h-[500px] w-full rounded-sm border border-[var(--color-border)] bg-[var(--color-bg)]"
          />
        );

      case "plotly_html":
        return (
          <iframe
            srcDoc={content ?? ""}
            sandbox="allow-scripts"
            title={artifact.title}
            className="h-[500px] w-full rounded-sm border border-[var(--color-border)] bg-[var(--color-bg)]"
          />
        );

      case "vega":
        return <VegaViewer content={content} />;

      case "checkpoint":
        return <FileInfoCard artifact={artifact} />;

      case "binary":
        return (
          <div className="space-y-3">
            {content != null && content.length > 0 && (
              <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-sm border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-4 text-sm leading-relaxed text-[var(--color-text)]">
                {content}
              </pre>
            )}
            <FileInfoCard artifact={artifact} />
            {artifact.storage_url && (
              <button
                type="button"
                onClick={() =>
                  openOrDownloadArtifact(artifact.storage_url, artifact.title, "download")
                }
                className="inline-flex items-center gap-2 rounded-sm bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--color-accent-hover)]"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 14 14"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M7 1v9M3.5 6.5 7 10l3.5-3.5M2 12h10" />
                </svg>
                download
              </button>
            )}
          </div>
        );

      case "diff_carousel":
        return <DiffCarouselViewer content={content} />;

      default:
        return (
          <p className="text-sm text-[var(--color-text-muted)]">
            unsupported artifact type: {artifact.artifact_type}
          </p>
        );
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h3 className="text-sm font-medium text-[var(--color-text)]">{artifact.title}</h3>
        <p className="mt-0.5 text-xs text-[var(--color-text-faint)]">
          {artifact.artifact_type} &middot; {new Date(artifact.created_at).toLocaleDateString()}
        </p>
      </div>

      {/* Viewer */}
      {renderByType()}

      {/* Storage URL download link */}
      {artifact.storage_url && artifact.artifact_type !== "binary" && (
        <button
          type="button"
          onClick={() =>
            openOrDownloadArtifact(artifact.storage_url, artifact.title, "download")
          }
          className="inline-flex items-center gap-1.5 text-xs text-[var(--color-accent)] transition-colors hover:text-[var(--color-accent-hover)]"
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 12 12"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M6 1v7M3 5l3 3 3-3M1.5 10h9" />
          </svg>
          download raw file
        </button>
      )}

      {/* Note */}
      {artifact.note && (
        <div className="rounded-sm border border-[var(--color-border)] bg-[var(--color-bg-subtle)] p-3">
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--color-text-faint)]">
            note
          </p>
          <pre className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-text-muted)]">
            {artifact.note}
          </pre>
        </div>
      )}
    </div>
  );
}
