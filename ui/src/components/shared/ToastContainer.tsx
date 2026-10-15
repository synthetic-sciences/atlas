import { createPortal } from "react-dom";
import { useUIStore } from "../../stores/uiStore.js";
import type { Toast } from "../../stores/uiStore.js";
import { FONT_MONO, RADIUS, Z } from "../../styles/tokens.js";

const borderColor: Record<Toast["type"], string> = {
  error: "var(--color-error)",
  success: "var(--color-success)",
  info: "var(--color-border-strong)",
};

// Theme-aware tint over the translucent surface so accents track
// --color-error / --color-success in both themes.
const background: Record<Toast["type"], string> = {
  error: "color-mix(in srgb, var(--color-error) 8%, var(--color-surface))",
  success: "color-mix(in srgb, var(--color-success) 8%, var(--color-surface))",
  info: "var(--color-surface)",
};

function ToastCard({ toast }: { toast: Toast }) {
  const removeToast = useUIStore((s) => s.removeToast);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "10px 14px",
        borderRadius: RADIUS,
        border: `1px solid ${borderColor[toast.type]}`,
        background: background[toast.type],
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        fontFamily: FONT_MONO,
        fontSize: 12,
        lineHeight: 1.5,
        color: "var(--color-text)",
        maxWidth: 340,
        minWidth: 220,
        boxShadow: "var(--shadow-md)",
        animation: "toast-fade-in 0.2s ease-out",
      }}
    >
      <span style={{ flex: 1, wordBreak: "break-word" }}>{toast.message}</span>
      <button
        type="button"
        onClick={() => removeToast(toast.id)}
        style={{
          // 44px hit area; negative margins keep the card compact.
          width: 44,
          height: 44,
          margin: "-15px -18px -15px 0",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: 0,
          color: "var(--color-text-muted)",
          fontSize: 14,
          lineHeight: 1,
          flexShrink: 0,
        }}
        aria-label="Dismiss toast"
      >
        &#x2715;
      </button>
    </div>
  );
}

export function ToastContainer() {
  const toasts = useUIStore((s) => s.toasts);

  if (toasts.length === 0) return null;

  return createPortal(
    <>
      <style>{`
        @keyframes toast-fade-in {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
      <div
        style={{
          position: "fixed",
          bottom: 24,
          right: 24,
          zIndex: Z.toast,
          display: "flex",
          flexDirection: "column-reverse",
          gap: 8,
          pointerEvents: "auto",
        }}
      >
        {toasts.map((toast) => (
          <ToastCard key={toast.id} toast={toast} />
        ))}
      </div>
    </>,
    document.body,
  );
}
