import { Network, Clock } from "lucide-react";

const SANS = "'Computer Modern', 'Latin Modern Roman', Georgia, 'Times New Roman', serif";
const HOVER_TRANSITION =
  "background 120ms ease, color 120ms ease, border-color 120ms ease";

export type ViewMode = "graph" | "timeline";

const TABS: { key: ViewMode; label: string; Icon: typeof Network }[] = [
  { key: "graph", label: "graph", Icon: Network },
  { key: "timeline", label: "timeline", Icon: Clock },
];

interface ViewModeToggleProps {
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
}

export function ViewModeToggle({ viewMode, setViewMode }: ViewModeToggleProps) {
  return (
    <div
      className="absolute z-10 flex items-center"
      style={{
        left: 16,
        top: 56,
        gap: 0,
        background: "var(--color-surface-solid)",
        border: "1px solid var(--color-border)",
        borderRadius: 2,
        padding: "3px 4px",
        boxShadow: "var(--glass-shadow)",
      }}
    >
      {TABS.map(({ key, label, Icon }) => {
        const active = viewMode === key;
        return (
          <button
            key={key}
            onClick={() => setViewMode(key)}
            style={{
              fontFamily: SANS,
              fontSize: "11px",
              fontWeight: 500,
              padding: "3px 10px",
              borderRadius: 2,
              border: "none",
              background: active ? "var(--color-bg-elevated)" : "transparent",
              color: active ? "var(--color-text)" : "var(--color-text-muted)",
              cursor: "pointer",
              transition: HOVER_TRANSITION,
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Icon size={12} />
            {label}
          </button>
        );
      })}
    </div>
  );
}
