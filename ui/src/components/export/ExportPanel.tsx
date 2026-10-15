import { useState } from "react";
import { api } from "../../api/client.js";

interface ExportPanelProps {
  nodeId: string;
  /** Called when the user wants to export the subgraph as JSON */
  onExportJson?: (nodeId: string) => Promise<Blob | null>;
  /** Called when the user wants to export a markdown summary */
  onExportMarkdown?: (nodeId: string) => Promise<Blob | null>;
}

export function ExportPanel({ nodeId, onExportJson, onExportMarkdown }: ExportPanelProps) {
  const [jsonLoading, setJsonLoading] = useState(false);
  const [mdLoading, setMdLoading] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function triggerDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function handleExportJson() {
    setJsonLoading(true);
    setError(null);
    try {
      if (onExportJson) {
        const blob = await onExportJson(nodeId);
        if (blob) triggerDownload(blob, `thesis-subgraph-${nodeId.slice(0, 8)}.json`);
      } else {
        const data = await api.exportSubgraph([nodeId]);
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        triggerDownload(blob, `thesis-subgraph-${nodeId.slice(0, 8)}.json`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "json export failed");
    } finally {
      setJsonLoading(false);
    }
  }

  async function handleExportMarkdown() {
    setMdLoading(true);
    setError(null);
    try {
      if (onExportMarkdown) {
        const blob = await onExportMarkdown(nodeId);
        if (blob) triggerDownload(blob, `thesis-summary-${nodeId.slice(0, 8)}.md`);
      } else {
        const data = await api.exportMarkdown([nodeId]);
        const markdown = typeof data === "string" ? data : (data as Record<string, unknown>).content as string || JSON.stringify(data, null, 2);
        const blob = new Blob([markdown], { type: "text/markdown" });
        triggerDownload(blob, `thesis-summary-${nodeId.slice(0, 8)}.md`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "markdown export failed");
    } finally {
      setMdLoading(false);
    }
  }

  async function handleExportPdf() {
    setPdfLoading(true);
    setError(null);
    try {
      const blob = await api.exportPdf([nodeId]);
      triggerDownload(blob, `thesis-summary-${nodeId.slice(0, 8)}.pdf`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "pdf export failed");
    } finally {
      setPdfLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-faint)]">
        export
      </h2>

      {error && (
        <p className="rounded border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-500" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
          {error}
        </p>
      )}

      <div className="space-y-2">
        {/* JSON export */}
        <button
          onClick={handleExportJson}
          disabled={jsonLoading}
          className="flex w-full items-center gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-left transition-colors hover:bg-[var(--color-bg-elevated)] disabled:opacity-50"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--color-accent-subtle)]">
            <svg
              width="18"
              height="18"
              viewBox="0 0 18 18"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-[var(--color-accent)]"
            >
              <path d="M5 3C4 3 3 4 3 5v1c0 1-1 2-2 2 1 0 2 1 2 2v1c0 1 1 2 2 2" />
              <path d="M13 3c1 0 2 1 2 2v1c0 1 1 2 2 2-1 0-2 1-2 2v1c0 1-1 2-2 2" />
            </svg>
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-[var(--color-text)]">
              {jsonLoading ? "exporting..." : "export as json"}
            </p>
            <p className="text-xs text-[var(--color-text-faint)]">
              full subgraph with nodes, edges, and artifacts
            </p>
          </div>
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="shrink-0 text-[var(--color-text-faint)]"
          >
            <path d="M7 1v9M3.5 6.5 7 10l3.5-3.5M2 12h10" />
          </svg>
        </button>

        {/* Markdown export */}
        <button
          onClick={handleExportMarkdown}
          disabled={mdLoading}
          className="flex w-full items-center gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-left transition-colors hover:bg-[var(--color-bg-elevated)] disabled:opacity-50"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--color-accent-subtle)]">
            <svg
              width="18"
              height="18"
              viewBox="0 0 18 18"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-[var(--color-accent)]"
            >
              <path d="M3 4h12v10H3z" />
              <path d="M6 8v4l1.5-2L9 12V8M11 8v4M11 8l2 2M13 8l-2 2" />
            </svg>
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-[var(--color-text)]">
              {mdLoading ? "exporting..." : "export as markdown"}
            </p>
            <p className="text-xs text-[var(--color-text-faint)]">
              human-readable summary of research findings
            </p>
          </div>
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="shrink-0 text-[var(--color-text-faint)]"
          >
            <path d="M7 1v9M3.5 6.5 7 10l3.5-3.5M2 12h10" />
          </svg>
        </button>

        {/* PDF export */}
        <button
          onClick={handleExportPdf}
          disabled={pdfLoading}
          className="flex w-full items-center gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-left transition-colors hover:bg-[var(--color-bg-elevated)] disabled:opacity-50"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--color-accent-subtle)]">
            <svg
              width="18"
              height="18"
              viewBox="0 0 18 18"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-[var(--color-accent)]"
            >
              <path d="M4 2h7l4 4v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" />
              <path d="M11 2v4h4" />
            </svg>
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-[var(--color-text)]">
              {pdfLoading ? "exporting..." : "export as pdf"}
            </p>
            <p className="text-xs text-[var(--color-text-faint)]">
              formatted pdf document for sharing
            </p>
          </div>
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="shrink-0 text-[var(--color-text-faint)]"
          >
            <path d="M7 1v9M3.5 6.5 7 10l3.5-3.5M2 12h10" />
          </svg>
        </button>
      </div>
    </div>
  );
}
