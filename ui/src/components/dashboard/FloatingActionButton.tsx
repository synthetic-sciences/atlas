import React, { useState, useCallback, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, FileJson, FilePlus } from "lucide-react";
import { useNodeStore } from "../../stores/nodeStore.js";
import { api } from "../../api/client.js";

const SANS = "'Computer Modern', 'Latin Modern Roman', Georgia, 'Times New Roman', serif";
const HOVER_TRANSITION = "background 120ms ease, color 120ms ease, border-color 120ms ease";

export function FloatingActionButton() {
  const nav = useNavigate();
  const fetchNodes = useNodeStore((s) => s.fetchNodes);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close popover on click outside
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as globalThis.Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const handleNewNode = useCallback(async () => {
    setLoading(true);
    try {
      const node = await api.stageCreate({});
      setOpen(false);
      await fetchNodes({ rootOnly: true });
      nav(`/nodes/${node.node_id}`);
    } catch (e) {
      console.error("Failed to create node:", e);
    }
    setLoading(false);
  }, [nav, fetchNodes]);

  const handleImportJson = useCallback(() => {
    fileRef.current?.click();
  }, []);

  const handleFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      await api.importSubgraph(data);
      setOpen(false);
      await fetchNodes({ rootOnly: true });
    } catch (err) {
      console.error("Failed to import subgraph:", err);
    }
    setLoading(false);
    if (fileRef.current) fileRef.current.value = "";
  }, [fetchNodes]);

  return (
    <div
      ref={containerRef}
      style={{ position: "fixed", bottom: 24, right: 24, zIndex: 100 }}
    >
      {/* Popover */}
      {open && (
        <div
          style={{
            position: "absolute",
            bottom: 52,
            right: 0,
            background: "var(--color-surface-solid)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            border: "1px solid var(--color-border)",
            borderRadius: 2,
            padding: "4px 0",
            minWidth: 160,
            boxShadow: "var(--glass-shadow)",
          }}
        >
          <button
            onClick={handleNewNode}
            disabled={loading}
            style={{
              all: "unset",
              display: "flex",
              alignItems: "center",
              gap: 8,
              width: "100%",
              padding: "8px 14px",
              fontFamily: SANS,
              fontSize: 12,
              color: "var(--color-text-muted)",
              cursor: loading ? "wait" : "pointer",
              boxSizing: "border-box",
              transition: HOVER_TRANSITION,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-bg-elevated)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            <FilePlus size={14} style={{ color: "var(--color-text-faint)", flexShrink: 0 }} />
            new node
          </button>
          <button
            onClick={handleImportJson}
            disabled={loading}
            style={{
              all: "unset",
              display: "flex",
              alignItems: "center",
              gap: 8,
              width: "100%",
              padding: "8px 14px",
              fontFamily: SANS,
              fontSize: 12,
              color: "var(--color-text-muted)",
              cursor: loading ? "wait" : "pointer",
              boxSizing: "border-box",
              transition: HOVER_TRANSITION,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-bg-elevated)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            <FileJson size={14} style={{ color: "var(--color-text-faint)", flexShrink: 0 }} />
            import json
          </button>
        </div>
      )}

      {/* FAB button */}
      <button
        onClick={() => setOpen(!open)}
        aria-label={open ? "close create menu" : "open create menu"}
        aria-expanded={open}
        style={{
          width: 44,
          height: 44,
          borderRadius: "50%",
          border: "none",
          background: "var(--color-text)",
          color: "var(--color-bg)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
          boxShadow: "0 4px 16px rgba(0,0,0,0.3)",
          transition: "transform 120ms ease, opacity 120ms ease, background 120ms ease",
          transform: open ? "rotate(45deg)" : "rotate(0deg)",
        }}
      >
        <Plus size={20} />
      </button>

      {/* Hidden file input */}
      <input
        ref={fileRef}
        type="file"
        accept=".json"
        style={{ display: "none" }}
        onChange={handleFileChange}
      />
    </div>
  );
}
