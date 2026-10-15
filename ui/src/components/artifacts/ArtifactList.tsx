import { useState } from "react";
import type { Artifact, ArtifactType } from "../../api/types";
import { FilePreviewModal, type PreviewItem } from "../shared/FilePreviewModal";

interface ArtifactListProps {
  artifacts: Artifact[];
}

/* ------------------------------------------------------------------ */
/*  Type-to-icon mapping                                               */
/* ------------------------------------------------------------------ */

const TYPE_ICONS: Record<ArtifactType, string> = {
  text: "T",
  table: "t",
  json: "{}",
  image: "img",
  banner: "ban",
  html: "</>",
  plotly_html: "plt",
  vega: "vg",
  checkpoint: "ck",
  binary: "bin",
  diff_carousel: "dif",
};

const TYPE_LABELS: Record<ArtifactType, string> = {
  text: "text",
  table: "table",
  json: "json",
  image: "image",
  banner: "banner",
  html: "html",
  plotly_html: "plotly",
  vega: "vega",
  checkpoint: "checkpoint",
  binary: "binary",
  diff_carousel: "diff",
};

function toPreviewItem(a: Artifact): PreviewItem {
  return {
    title: a.title || a.filename || "file",
    mime: (a.metadata?.mime as string) ?? null,
    storageUrl: a.storage_url ?? null,
    storagePath: a.storage_path ?? null,
    metadata: a.metadata ?? null,
    sizeBytes: (a.metadata?.size_bytes as number) ?? null,
  };
}

export function ArtifactList({ artifacts }: ArtifactListProps) {
  // Clicking a row opens the shared in-app previewer (same modal as the chat
  // asset cards) — authed fetch + typed rendering, no new-tab/auth dance.
  const [preview, setPreview] = useState<PreviewItem | null>(null);

  if (artifacts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] py-12">
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-[var(--color-text-faint)]"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
          <path d="M14 2v6h6" />
        </svg>
        <p className="mt-3 text-sm text-[var(--color-text-muted)]">no artifacts yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-faint)]">
          artifacts ({artifacts.length})
        </h2>
      </div>

      {/* List */}
      <div className="divide-y divide-[var(--color-border)] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
        {artifacts.map((artifact) => (
          <button
            key={artifact.artifact_id}
            onClick={() => setPreview(toPreviewItem(artifact))}
            className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--color-bg-elevated)]"
            title={`Preview ${artifact.title}`}
          >
            {/* Type icon */}
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[var(--color-accent-subtle)] text-xs font-semibold text-[var(--color-accent)]">
              {TYPE_ICONS[artifact.artifact_type]}
            </span>

            {/* Title + note preview */}
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-[var(--color-text)]">
                {artifact.title}
              </p>
              {artifact.note && (
                <p className="mt-0.5 truncate text-xs text-[var(--color-text-faint)]">
                  {artifact.note}
                </p>
              )}
            </div>

            {/* Type badge */}
            <span className="shrink-0 rounded-full bg-[var(--color-bg-elevated)] px-2 py-0.5 text-xs text-[var(--color-text-muted)]">
              {TYPE_LABELS[artifact.artifact_type]}
            </span>

            {/* Open indicator */}
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
              <path d="M5.25 3.5 8.75 7l-3.5 3.5" />
            </svg>
          </button>
        ))}
      </div>

      <FilePreviewModal item={preview} open={!!preview} onClose={() => setPreview(null)} />
    </div>
  );
}
