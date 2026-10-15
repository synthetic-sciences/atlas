import { useState } from "react";
import type { Node } from "../../api/types";

const MONO = "'JetBrains Mono', monospace";
const SANS = "'Computer Modern', 'Latin Modern Roman', Georgia, 'Times New Roman', serif";
const HOVER_TRANSITION = "background 120ms ease, color 120ms ease, border-color 120ms ease";

type SortMode = "created" | "updated";

interface GraphListPanelProps {
  rootGraphs: Node[];
  activeGraphId: string | null;
  activeGraphName: string;
  nodeCount: number;
  onSelectGraph: (nodeId: string) => void;
}

export function GraphListPanel({
  rootGraphs,
  activeGraphId,
  activeGraphName,
  nodeCount,
  onSelectGraph,
}: GraphListPanelProps) {
  const [graphListOpen, setGraphListOpen] = useState(false);
  const [sortMode, setSortMode] = useState<SortMode>("updated");

  const sortedGraphs = rootGraphs.slice().sort((a, b) => {
    const dateA = sortMode === "created" ? a.created_at : a.updated_at;
    const dateB = sortMode === "created" ? b.created_at : b.updated_at;
    return (dateB || "").localeCompare(dateA || "");
  });

  return (
    <>
      {/* Graph list - compact ledger popup, bottom-left */}
      {graphListOpen && (
        <div
          className="absolute bottom-16 left-4 z-20"
          style={{
            width: 300,
            maxHeight: "60vh",
            display: "flex",
            flexDirection: "column",
            background: "var(--color-surface-solid)",
            border: "1px solid var(--color-border)",
            borderRadius: 2,
            boxShadow: "0 18px 50px rgba(0,0,0,0.14)",
            overflow: "hidden",
          }}
        >
          {/* Sort toggle header */}
          <div
            style={{
              padding: "8px 12px",
              borderBottom: "1px solid var(--color-border)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span
              style={{
                fontFamily: SANS,
                fontSize: "9px",
                fontWeight: 500,
                letterSpacing: "0.1em",
                color: "var(--color-text-faint)",
              }}
            >
              graphs
            </span>
            <div style={{ display: "flex", gap: 2 }}>
              {(["created", "updated"] as SortMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setSortMode(mode)}
                  style={{
                    fontFamily: SANS,
                    fontSize: "9px",
                    fontWeight: 500,
                    padding: "2px 8px",
                    borderRadius: 2,
                    border: "none",
                    background:
                      sortMode === mode
                        ? "var(--color-bg-elevated)"
                        : "transparent",
                    color:
                      sortMode === mode
                        ? "var(--color-text)"
                        : "var(--color-text-muted)",
                    cursor: "pointer",
                    transition: HOVER_TRANSITION,
                  }}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>

          {/* Scrollable graph list */}
          <div
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "4px 0",
            }}
          >
            {sortedGraphs.map((g) => {
              const isActive = g.node_id === activeGraphId;
              const childCount = isActive ? nodeCount : 0;
              return (
                <button
                  key={g.node_id}
                  onClick={() => {
                    onSelectGraph(g.node_id);
                    setGraphListOpen(false);
                  }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    width: "100%",
                    textAlign: "left",
                    padding: "6px 12px",
                    fontFamily: SANS,
                    fontSize: "12px",
                    fontWeight: isActive ? 500 : 400,
                    color: isActive
                      ? "var(--color-text)"
                      : "var(--color-text-muted)",
                    background: isActive
                      ? "var(--color-bg-elevated)"
                      : "transparent",
                    border: "none",
                    cursor: "pointer",
                    transition: HOVER_TRANSITION,
                  }}
                  onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = "var(--color-bg-elevated)"; }}
                  onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = "transparent"; }}
                >
                  <span
                    aria-hidden
                    title={g.is_owner ? "owned" : "shared privately"}
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: "50%",
                      flexShrink: 0,
                      marginRight: 8,
                      background: g.is_owner
                        ? "var(--color-border-strong)"
                        : "var(--color-accent)",
                    }}
                  />
                  <span
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      flex: 1,
                    }}
                  >
                    {g.title || g.node_id.slice(0, 8)}
                  </span>
                  {isActive && childCount > 0 && (
                    <span
                      style={{
                        fontFamily: MONO,
                        fontSize: "9px",
                        fontWeight: 500,
                        padding: "1px 6px",
                        borderRadius: 2,
                        background: "var(--color-accent-subtle)",
                        color: "var(--color-text-faint)",
                        marginLeft: 6,
                        flexShrink: 0,
                      }}
                    >
                      {childCount}
                    </span>
                  )}
                </button>
              );
            })}
            {sortedGraphs.length === 0 && (
              <div
                style={{
                  padding: "16px 12px",
                  fontFamily: SANS,
                  fontSize: "11px",
                  color: "var(--color-text-faint)",
                  textAlign: "center",
                }}
              >
                no graphs yet
              </div>
            )}
          </div>
        </div>
      )}

      {/* Graph list toggle button - bottom-left */}
      <button
        className="absolute left-4 bottom-4 z-10 flex items-center gap-2"
        onClick={() => setGraphListOpen(!graphListOpen)}
        style={{
          background: "var(--color-surface-solid)",
          border: "1px solid var(--color-border)",
          borderRadius: 2,
          padding: "5px 12px",
          boxShadow: "0 12px 28px rgba(0,0,0,0.10)",
          cursor: "pointer",
          fontFamily: SANS,
          fontSize: 11,
          color: graphListOpen ? "var(--color-text)" : "var(--color-text-muted)",
          transition: HOVER_TRANSITION,
        }}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M2 3h8M2 6h6M2 9h4" />
        </svg>
        {activeGraphName}
      </button>
    </>
  );
}
