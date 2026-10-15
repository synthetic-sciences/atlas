import { memo } from "react";
import type { NodeProps } from "@xyflow/react";

/**
 * GroupFrameNode — the background container the adaptive layout draws behind a
 * cluster (a tier / track / wave / detected group). It is non-interactive and
 * sits below the research cards; its only job is to make the partition legible
 * with a hairline frame + a mono label. Soft Porcelain.
 */
function GroupFrameNodeImpl({ data }: NodeProps) {
  const d = data as { label?: string; count?: number };
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        border: "1px solid var(--color-border)",
        borderRadius: 3,
        background: "var(--color-bg-subtle)",
        boxSizing: "border-box",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          padding: "12px 16px",
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--color-text-muted)",
        }}
      >
        <span style={{ fontWeight: 600, color: "var(--color-text)" }}>{d.label ?? "group"}</span>
        {typeof d.count === "number" && (
          <span style={{ color: "var(--color-text-faint)", fontSize: 10 }}>{d.count}</span>
        )}
      </div>
    </div>
  );
}

export const GroupFrameNode = memo(GroupFrameNodeImpl);
