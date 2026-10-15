import type { CSSProperties } from "react";

export const FONT_MONO = "'SFMono-Regular', 'SF Mono', Menlo, Consolas, ui-monospace, monospace";
// Default body font: Computer Modern (self-hosted in /fonts/cmc/, see styles/index.css for @font-face).
export const FONT_SANS = "'Computer Modern', 'Latin Modern Roman', Georgia, 'Times New Roman', serif";
export const FONT_SERIF = "'Computer Modern', 'Latin Modern Roman', Georgia, 'Times New Roman', serif";
// Native UI stack for dense data grids and terminal-style chrome.
export const FONT_UI_SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

export const RADIUS = 2;

export const Z = {
  header: 20,
  sticky: 50,
  fab: 100,
  overlay: 200,
  modal: 300,
  toast: 400,
} as const;

export const ICON_SIZE = {
  xs: 11,
  sm: 12,
  md: 13,
  lg: 14,
  xl: 16,
} as const;

export const pageContainer: CSSProperties = {
  padding: "32px 40px",
  maxWidth: 1200,
  margin: "0 auto",
  fontFamily: FONT_SANS,
};

export const pageTitle: CSSProperties = {
  fontFamily: FONT_SANS,
  fontSize: 20,
  fontWeight: 500,
  letterSpacing: "-0.01em",
  color: "var(--color-text)",
  margin: 0,
};

export const pageDesc: CSSProperties = {
  fontFamily: FONT_SANS,
  fontSize: 12,
  color: "var(--color-text-muted)",
  margin: "4px 0 0",
  lineHeight: 1.5,
};

export const sectionTitle: CSSProperties = {
  fontFamily: FONT_SANS,
  fontSize: 11,
  fontWeight: 500,
  letterSpacing: "0.01em",
  color: "var(--color-text-faint)",
};

export const cardStyle: CSSProperties = {
  background: "var(--color-surface-solid)",
  border: "1px solid var(--color-border)",
  borderRadius: RADIUS,
  padding: "14px 16px",
};

export const inputStyle: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 12,
  padding: "8px 12px",
  borderRadius: RADIUS,
  border: "1px solid var(--color-border)",
  background: "var(--color-accent-subtle)",
  color: "var(--color-text)",
  width: "100%",
};

export const errorBanner: CSSProperties = {
  fontFamily: FONT_MONO,
  fontSize: 11,
  color: "var(--color-error)",
  background: "var(--color-error-muted)",
  border: "1px solid var(--color-error)",
  borderRadius: RADIUS,
  padding: "8px 12px",
  lineHeight: 1.5,
};

export const emptyStateText: CSSProperties = {
  fontFamily: FONT_SANS,
  fontSize: 12,
  color: "var(--color-text-muted)",
  textAlign: "center",
  padding: 48,
  lineHeight: 1.6,
};
