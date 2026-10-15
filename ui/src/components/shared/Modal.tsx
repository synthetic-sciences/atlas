import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { FONT_SANS, ICON_SIZE, Z } from "../../styles/tokens";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  maxWidth?: number;
  children: ReactNode;
  "data-testid"?: string;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusableIn(panel: HTMLElement): HTMLElement[] {
  return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
}

export function Modal(props: ModalProps) {
  // The dialog body is a separate component that only exists while open, so
  // each opening starts from a fresh render: consumers that keep <Modal>
  // mounted and toggle ``open`` (ShortcutHelp, FilePreviewModal) still get
  // the opener captured at the moment the dialog appears, not at first mount.
  if (!props.open) return null;
  return <OpenModal {...props} />;
}

function OpenModal({
  onClose,
  title,
  maxWidth = 520,
  children,
  "data-testid": testId,
}: ModalProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  // Capture the opener during the first render, before the dialog subtree
  // commits. A child's autoFocus (ConfirmDialog's Cancel/Confirm) runs during
  // commit, so by the time any effect fires document.activeElement is already
  // the dialog's own button and the real opener would be lost.
  const [opener] = useState<HTMLElement | null>(() =>
    typeof document === "undefined" ? null : (document.activeElement as HTMLElement | null),
  );

  // Move focus into the dialog on open (children that set autoFocus already
  // own it) and hand it back to the opener when the dialog goes away.
  useEffect(() => {
    const panel = panelRef.current;
    if (panel && !panel.contains(document.activeElement)) {
      (focusableIn(panel)[0] ?? panel).focus();
    }
    return () => {
      // Passive cleanups run after the portal's DOM is removed, so a
      // disconnected panel means a real close. StrictMode's simulated
      // unmount leaves it attached and must not bounce focus around.
      if (panel?.isConnected) return;
      if (opener && opener.isConnected) opener.focus();
    };
  }, [opener]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      // Keep Tab inside the dialog while it is open.
      if (e.key !== "Tab" || !panelRef.current) return;
      const items = focusableIn(panelRef.current);
      if (items.length === 0) {
        e.preventDefault();
        panelRef.current.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || !panelRef.current.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !panelRef.current.contains(active))) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? titleId : undefined}
      data-testid={testId}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: Z.modal,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0, 0, 0, 0.5)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
        padding: 20,
        animation: "fade-in 160ms ease-out",
      }}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth,
          maxHeight: "calc(100vh - 80px)",
          background: "var(--color-surface-solid)",
          border: "1px solid var(--color-border)",
          borderRadius: 2,
          boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          fontFamily: FONT_SANS,
          animation: "scale-in 160ms cubic-bezier(0.16, 1, 0.3, 1)",
          outline: "none",
        }}
      >
        {title && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "14px 16px",
              borderBottom: "1px solid var(--color-border)",
            }}
          >
            <h2
              id={titleId}
              style={{
                margin: 0,
                fontSize: 13,
                fontWeight: 500,
                color: "var(--color-text)",
              }}
            >
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              style={{
                // 44px hit area; negative margins keep the header compact.
                width: 44,
                height: 44,
                margin: "-12px -14px -12px 0",
                background: "transparent",
                border: "none",
                color: "var(--color-text-muted)",
                cursor: "pointer",
                padding: 0,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <X size={ICON_SIZE.lg} />
            </button>
          </div>
        )}
        <div style={{ overflow: "auto", flex: 1 }}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}
