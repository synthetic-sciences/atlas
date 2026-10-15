/**
 * Shimmer-animated skeleton components for Suspense fallbacks.
 * Shows structured gray placeholders instead of blank white space while pages load.
 */

import type { CSSProperties } from "react";
import { FONT_MONO } from "../../styles/tokens.js";

// ---------------------------------------------------------------------------
// Keyframes - injected once via <style>
// ---------------------------------------------------------------------------

const KEYFRAMES_ID = "thesis-shimmer-keyframes";

function ensureKeyframes() {
  if (typeof document === "undefined") return;
  if (document.getElementById(KEYFRAMES_ID)) return;
  const style = document.createElement("style");
  style.id = KEYFRAMES_ID;
  style.textContent = `
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
@keyframes thesis-pulse-dot{
  0%,80%,100%{opacity:0.18;transform:scale(0.85)}
  40%{opacity:0.85;transform:scale(1)}
}
@keyframes thesis-graph-grid-pan{
  0%{background-position:0 0,0 0}
  100%{background-position:32px 32px,32px 32px}
}
@keyframes thesis-fade-in{
  from{opacity:0}to{opacity:1}
}
`;
  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// Base shimmer style
// ---------------------------------------------------------------------------

const shimmerStyle: CSSProperties = {
  background:
    "linear-gradient(90deg, var(--color-surface) 25%, var(--color-border) 50%, var(--color-surface) 75%)",
  backgroundSize: "200% 100%",
  animation: "shimmer 1.5s ease-in-out infinite",
  borderRadius: 2,
};

// ---------------------------------------------------------------------------
// SkeletonLine - single line placeholder
// ---------------------------------------------------------------------------

interface SkeletonLineProps {
  width?: string;
  height?: number;
}

export function SkeletonLine({ width = "100%", height = 12 }: SkeletonLineProps) {
  ensureKeyframes();
  return (
    <div
      style={{
        ...shimmerStyle,
        width,
        height,
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// SkeletonBlock - multiple lines (paragraph placeholder)
// ---------------------------------------------------------------------------

interface SkeletonBlockProps {
  lines?: number;
}

export function SkeletonBlock({ lines = 4 }: SkeletonBlockProps) {
  ensureKeyframes();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {Array.from({ length: lines }, (_, i) => (
        <SkeletonLine
          key={i}
          width={i === lines - 1 ? "60%" : "100%"}
          height={12}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PageSkeleton - full page skeleton mirroring the real dashboard page shell
// (.dashboard-page > .dashboard-wrap > .page-header) so nothing jumps when
// the loaded page swaps in.
// ---------------------------------------------------------------------------

export function PageSkeleton() {
  ensureKeyframes();
  return (
    <div className="dashboard-page" aria-busy="true">
      <div className="dashboard-wrap dashboard-stack">
        <header className="page-header" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <SkeletonLine width="90px" height={11} />
          <SkeletonLine width="220px" height={28} />
          <SkeletonLine width="60%" height={13} />
        </header>
        <SkeletonBlock lines={4} />
        <SkeletonBlock lines={6} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// GraphSkeleton - quiet, design-aligned graph loading state.
//
// The previous version drew five gray rectangles in a fixed pattern that
// looked like real (broken) nodes - users mistook them for the actual graph.
// This version is intentionally non-representational: a faint dotted grid
// with a centered status indicator. It signals "loading" without pretending
// to be content, and matches the Obsidian Glass design language.
// ---------------------------------------------------------------------------

export function GraphSkeleton() {
  ensureKeyframes();

  const dotBase: CSSProperties = {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "var(--color-text-faint)",
    animation: "thesis-pulse-dot 1.4s ease-in-out infinite",
  };

  return (
    <div
      style={{
        position: "relative",
        flex: 1,
        minHeight: 0,
        width: "100%",
        height: "100%",
        background: "var(--color-bg)",
        overflow: "hidden",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        animation: "thesis-fade-in 220ms ease-out both",
      }}
    >
      {/* Faint dotted grid, slowly drifting. Two layers offset for depth. */}
      <div
        aria-hidden
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `
            radial-gradient(circle at 1px 1px, var(--color-border) 1px, transparent 0),
            radial-gradient(circle at 1px 1px, var(--color-border) 1px, transparent 0)
          `,
          backgroundSize: "32px 32px, 64px 64px",
          backgroundPosition: "0 0, 16px 16px",
          opacity: 0.35,
          maskImage:
            "radial-gradient(ellipse at center, black 35%, transparent 78%)",
          WebkitMaskImage:
            "radial-gradient(ellipse at center, black 35%, transparent 78%)",
          animation: "thesis-graph-grid-pan 12s linear infinite",
        }}
      />

      {/* Centered status - three pulsing dots over a tiny mono caption. */}
      <div
        style={{
          position: "relative",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 12,
          padding: "14px 20px",
          fontFamily: FONT_MONO,
          fontSize: 10,
          letterSpacing: "0.18em",
          color: "var(--color-text-faint)",
          userSelect: "none",
        }}
      >
        <div style={{ display: "flex", gap: 6 }}>
          <span style={{ ...dotBase, animationDelay: "0s" }} />
          <span style={{ ...dotBase, animationDelay: "0.18s" }} />
          <span style={{ ...dotBase, animationDelay: "0.36s" }} />
        </div>
        <span>loading graph</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ListSkeleton - table/list with row placeholders
// ---------------------------------------------------------------------------

interface ListSkeletonProps {
  rows?: number;
}

export function ListSkeleton({ rows = 8 }: ListSkeletonProps) {
  ensureKeyframes();
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        fontFamily: FONT_MONO,
      }}
    >
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "6px 12px",
            borderBottom: "1px solid var(--color-border)",
          }}
        >
          {/* Kind chip placeholder */}
          <SkeletonLine width="36px" height={16} />
          {/* Title placeholder */}
          <SkeletonLine width={`${50 + (i % 3) * 15}%`} height={13} />
          {/* Right-side badge */}
          <div style={{ marginLeft: "auto" }}>
            <SkeletonLine width="24px" height={12} />
          </div>
        </div>
      ))}
    </div>
  );
}
