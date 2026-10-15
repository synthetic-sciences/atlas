import type { CSSProperties } from "react";
import { AlertCircle, AlertTriangle } from "lucide-react";
import { FONT_MONO, ICON_SIZE, RADIUS } from "../../styles/tokens";

interface ErrorAlertProps {
  message: string;
  tone?: "error" | "warning";
  compact?: boolean;
  style?: CSSProperties;
}

export function ErrorAlert({
  message,
  tone = "error",
  compact = false,
  style,
}: ErrorAlertProps) {
  const color = tone === "warning" ? "var(--color-warning)" : "var(--color-error)";
  const bg = tone === "warning" ? "var(--color-warning-muted)" : "var(--color-error-muted)";
  const Icon = tone === "warning" ? AlertTriangle : AlertCircle;

  return (
    <div
      role="alert"
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 8,
        padding: compact ? "6px 10px" : "8px 12px",
        border: `1px solid ${color}`,
        background: bg,
        color,
        borderRadius: RADIUS,
        fontFamily: FONT_MONO,
        fontSize: 11,
        lineHeight: 1.5,
        ...style,
      }}
    >
      <Icon size={ICON_SIZE.md} style={{ flexShrink: 0, marginTop: 1 }} />
      <span style={{ wordBreak: "break-word" }}>{message}</span>
    </div>
  );
}
