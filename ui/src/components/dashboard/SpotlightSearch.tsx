import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { nodesApi } from "../../api/nodes.js";
import type { Node } from "../../api/types.js";

const MONO = "'JetBrains Mono', monospace";
const SANS = "'Computer Modern', 'Latin Modern Roman', Georgia, 'Times New Roman', serif";
const HOVER_TRANSITION = "background 120ms ease, color 120ms ease, border-color 120ms ease";

// Search scope. Every option runs a server-side graph-node search, optionally
// filtered by kind; this searches the whole graph rather than just roots that
// happen to be loaded in the browser.
type Scope = "all" | "empirical" | "hypothesis" | "insight" | "decision";
const SCOPES: { key: Scope; label: string }[] = [
  { key: "all", label: "all" },
  { key: "empirical", label: "runs" },
  { key: "hypothesis", label: "hypotheses" },
  { key: "insight", label: "insights" },
  { key: "decision", label: "decisions" },
];

export function SpotlightSearch() {
  const navigate = useNavigate();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<Scope>("all");
  const [nodeResults, setNodeResults] = useState<Node[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const reqRef = useRef(0); // guards against out-of-order async responses

  // Cmd+K / Ctrl+K toggles graph search; Esc closes it.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((p) => !p);
      }
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setNodeResults([]);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Debounced graph search, ignoring stale responses via reqRef.
  useEffect(() => {
    const q = query.trim();
    if (!open || !q) {
      setNodeResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const myReq = ++reqRef.current;
    const handle = setTimeout(async () => {
      const nodes = await nodesApi
        .listNodes({
          title: q,
          per_page: 20,
          scope: "owned_or_shared_private",
          ...(scope !== "all" ? { kind: scope } : {}),
        })
        .then((r) => r.nodes ?? [])
        .catch(() => [] as Node[]);
      if (reqRef.current !== myReq) return; // a newer query superseded this one
      setNodeResults(nodes);
      setLoading(false);
    }, 250);
    return () => clearTimeout(handle);
  }, [query, scope, open]);

  const goNode = (id: string) => {
    navigate(`/nodes/${id}`);
    setOpen(false);
  };
  const hasResults = nodeResults.length > 0;
  const q = query.trim();

  return (
    <>
      <button
        className="absolute right-4 top-4 z-10 flex items-center gap-1"
        onClick={() => setOpen(true)}
        style={triggerStyle}
      >
        <Search size={13} style={{ color: "var(--color-text-faint)", flexShrink: 0 }} />
        <span>search</span>
        <kbd style={kbdStyle}>{"⌘"}K</kbd>
      </button>

      {open && (
        <div onClick={() => setOpen(false)} style={overlayStyle}>
          <div onClick={(e) => e.stopPropagation()} style={modalStyle}>
            {/* input */}
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 16px" }}>
              <Search size={15} style={{ color: "var(--color-text-faint)", flexShrink: 0 }} />
              <input
                ref={inputRef}
                type="text"
                placeholder="Search nodes, runs, hypotheses, and ideas…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                style={inputStyle}
              />
              {loading && <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--color-text-faint)" }}>…</span>}
            </div>

            {/* scope filter chips */}
            <div style={chipRowStyle}>
              {SCOPES.map((s) => (
                <button
                  key={s.key}
                  onClick={() => setScope(s.key)}
                  style={chipStyle(scope === s.key)}
                >
                  {s.label}
                </button>
              ))}
            </div>

            <div style={{ height: 1, background: "var(--color-border)" }} />

            {/* results */}
            <div style={{ maxHeight: 380, overflowY: "auto" }}>
              {nodeResults.length > 0 && (
                <Section label={scope === "all" ? "nodes" : SCOPES.find((s) => s.key === scope)?.label}>
                  {nodeResults.map((n) => (
                    <ResultRow
                      key={n.node_id}
                      title={n.title || n.node_id.slice(0, 8)}
                      chip={n.kind}
                      hint={n.slug_name}
                      onClick={() => goNode(n.node_id)}
                    />
                  ))}
                </Section>
              )}
              {q && !loading && !hasResults && (
                <div style={emptyStyle}>no results for “{q}”</div>
              )}
              {!q && <div style={emptyStyle}>search across your private graph nodes</div>}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Section({ label, children }: { label?: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: "6px 0" }}>
      {label && (
        <div style={{ padding: "4px 16px", fontFamily: MONO, fontSize: 9, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--color-text-faint)" }}>
          {label}
        </div>
      )}
      {children}
    </div>
  );
}

function ResultRow({
  title, chip, hint, onClick,
}: { title: string; chip?: string | null; hint?: string | null; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        all: "unset",
        display: "flex",
        alignItems: "center",
        gap: 8,
        width: "100%",
        padding: "8px 16px",
        fontFamily: SANS,
        fontSize: 12,
        color: "var(--color-text-muted)",
        cursor: "pointer",
        boxSizing: "border-box",
        transition: HOVER_TRANSITION,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-bg-elevated)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
    >
      <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</span>
      {chip && (
        <span style={{ fontSize: 9, fontWeight: 500, padding: "1px 6px", borderRadius: 2, background: "var(--color-accent-subtle)", color: "var(--color-text-faint)", flexShrink: 0 }}>
          {chip}
        </span>
      )}
      {hint && <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--color-text-faint)", flexShrink: 0 }}>{hint}</span>}
    </button>
  );
}

/* ── styles ── */
const triggerStyle: React.CSSProperties = {
  background: "var(--color-surface-solid)", border: "1px solid var(--color-border)", borderRadius: 2,
  padding: "5px 12px", boxShadow: "var(--glass-shadow)", cursor: "pointer", fontFamily: SANS, fontSize: 11,
  color: "var(--color-text-muted)", display: "flex", alignItems: "center", gap: 6, transition: HOVER_TRANSITION,
};
const kbdStyle: React.CSSProperties = {
  fontFamily: MONO, fontSize: 9, padding: "1px 4px", borderRadius: 2, border: "1px solid var(--color-border)",
  color: "var(--color-text-faint)", marginLeft: 4,
};
const overlayStyle: React.CSSProperties = {
  position: "fixed", inset: 0, zIndex: 200, background: "rgba(0,0,0,0.5)",
  display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: "18vh",
};
const modalStyle: React.CSSProperties = {
  background: "var(--color-surface-solid)", border: "1px solid var(--color-border)", borderRadius: 2,
  maxWidth: 560, width: "90%", boxShadow: "0 16px 48px rgba(0,0,0,0.3)", overflow: "hidden",
};
const inputStyle: React.CSSProperties = {
  all: "unset", flex: 1, fontFamily: MONO, fontSize: 15, color: "var(--color-text)",
  caretColor: "var(--color-text-muted)", boxSizing: "border-box",
};
const chipRowStyle: React.CSSProperties = {
  display: "flex", gap: 4, flexWrap: "wrap", padding: "0 12px 10px", alignItems: "center",
};
const chipStyle = (active: boolean): React.CSSProperties => ({
  all: "unset", cursor: "pointer", fontFamily: MONO, fontSize: 10, padding: "3px 9px", borderRadius: 2,
  border: "1px solid var(--color-border)",
  background: active ? "var(--color-surface-solid)" : "transparent",
  color: active ? "var(--color-text)" : "var(--color-text-faint)",
  boxShadow: active ? "var(--shadow-xs)" : "none", transition: HOVER_TRANSITION,
});
const emptyStyle: React.CSSProperties = {
  padding: "20px 16px", fontFamily: SANS, fontSize: 12, color: "var(--color-text-faint)", textAlign: "center",
};
