import { useState } from "react";
import { Lock } from "lucide-react";

import type { Collaborator, SharingInfo, SharingMode } from "../../api/types.js";
import { FEATURE_PUBLIC_GRAPHS } from "../../lib/config.js";
import { FONT_MONO as mono } from "../../styles/tokens.js";

interface SharingPanelProps {
  sharingInfo: SharingInfo;
  onChangeMode?: (mode: SharingMode) => void;
  onAddCollaborator?: (email: string, role: Collaborator["role"]) => void;
  onRemoveCollaborator?: (email: string) => void;
}

const MODES: { value: SharingMode; label: string; desc: string }[] = [
  { value: "private", label: "private", desc: "only you and collaborators" },
  { value: "unlisted", label: "unlisted", desc: "anyone with the link" },
  { value: "public", label: "public", desc: "discoverable by anyone" },
];

const ROLES: Collaborator["role"][] = ["viewer", "editor", "admin"];

const lbl: React.CSSProperties = {
  fontFamily: mono, fontSize: 11, fontWeight: 500,
  letterSpacing: "0.06em",
  color: "var(--color-text-muted)", marginBottom: 6,
};

const input: React.CSSProperties = {
  fontFamily: mono, fontSize: 11,
  minHeight: 44, padding: "6px 8px", borderRadius: 2,
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
};

export function SharingPanel({
  sharingInfo,
  onChangeMode,
  onAddCollaborator,
  onRemoveCollaborator,
}: SharingPanelProps) {
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState<Collaborator["role"]>("viewer");
  // This is derived from the graph owner's active legacy entitlement by the
  // same backend that gates mutations. Missing data stays fail-closed during
  // a rolling deploy.
  const collaborationEnabled = sharingInfo.collaboration_enabled === true;
  const visibleModes = FEATURE_PUBLIC_GRAPHS
    ? MODES
    : MODES.filter((mode) => mode.value === "private");
  const effectiveMode: SharingMode = FEATURE_PUBLIC_GRAPHS
    ? sharingInfo.sharing_mode
    : "private";
  const isOwner = !!sharingInfo.is_owner;
  const canManage = sharingInfo.effective.can_admin === true;
  // When the server reports no collaboration entitlement, existing
  // collaborator rows remain visible but are treated as frozen.
  const isFrozen =
    isOwner &&
    !collaborationEnabled &&
    sharingInfo.collaborators.length > 0;
  // Prevent additions when collaboration is unavailable. Public visibility
  // remains independently gated by FEATURE_PUBLIC_GRAPHS.
  const collaborationUnavailable = isOwner && !collaborationEnabled;
  // Future public modes remain locked without a collaboration entitlement.
  // Never disable the stored mode so a legacy graph can return to private.
  const isModeLocked = (mode: SharingMode): boolean =>
    !canManage || (
      collaborationUnavailable &&
      mode !== "private" &&
      mode !== sharingInfo.sharing_mode
    );
  const mutationUnavailable = !canManage || !collaborationEnabled;

  function handleAdd() {
    if (!newEmail.trim() || mutationUnavailable) return;
    onAddCollaborator?.(newEmail.trim(), newRole);
    setNewEmail("");
    setNewRole("viewer");
  }

  return (
    <div className="sharing-panel" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div
        style={{
          border: "1px solid var(--color-border)",
          borderRadius: 2,
          padding: "8px 10px",
          background: "var(--color-bg-subtle)",
          fontFamily: mono,
          fontSize: 11,
          lineHeight: 1.45,
          color: "var(--color-text-muted)",
        }}
      >
        Sharing applies to the whole graph, not this node alone. Every node in
        the project inherits the root graph's visibility and collaborators.
        {sharingInfo.requested_node_id && sharingInfo.project_id && sharingInfo.requested_node_id !== sharingInfo.project_id && (
          <>
            {" "}Editing root <span style={{ color: "var(--color-text)" }}>{sharingInfo.project_id.slice(0, 8)}</span>.
          </>
        )}
      </div>

      {collaborationUnavailable && (
        <div
          style={{
            border: "1px solid var(--color-border)",
            borderRadius: 2,
            padding: "8px 10px",
            background: "var(--color-bg-elevated)",
            fontFamily: mono,
            fontSize: 11,
            lineHeight: 1.5,
            color: "var(--color-text-muted)",
          }}
        >
          {isFrozen ? (
            <>
              <strong style={{ color: "var(--color-text)" }}>
                private collaboration frozen
              </strong>{" "}
              — existing collaborators can still view but not edit this graph.
              New collaboration plans are coming soon.
            </>
          ) : (
            <>
              Private collaboration is <strong style={{ color: "var(--color-text)" }}>coming soon</strong>.
              Grandfathered plans keep their recorded collaboration benefits.
            </>
          )}
        </div>
      )}

      {/* Visibility is private-only unless the reversible public-graphs flag is enabled. */}
      <div>
        <p style={lbl}>visibility</p>
        <div
          style={{
            display: "inline-flex",
            borderRadius: 2,
            border: "1px solid var(--color-border)",
            overflow: "hidden",
          }}
        >
          {visibleModes.map((m) => {
            const on = effectiveMode === m.value;
            const locked = isModeLocked(m.value);
            return (
              <button
                key={m.value}
                onClick={() => !locked && onChangeMode?.(m.value)}
                disabled={locked}
                title={locked
                  ? canManage
                    ? "Private collaboration is not currently available"
                    : "Administrator access is required"
                  : m.desc}
                style={{
                  fontFamily: mono, fontSize: 11, fontWeight: 500,
                  minHeight: 44, padding: "5px 12px", border: "none",
                  cursor: locked ? "not-allowed" : "pointer",
                  background: on ? "var(--color-accent-subtle)" : "transparent",
                  color: on
                    ? "var(--color-text)"
                    : locked
                      ? "var(--color-text-faint)"
                      : "var(--color-text-faint)",
                  opacity: locked ? 0.5 : 1,
                  transition: "background-color 120ms, color 120ms, opacity 120ms",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                }}
              >
                {locked && <Lock size={9} strokeWidth={2.2} aria-hidden />}
                {m.label}
              </button>
            );
          })}
        </div>
        <p style={{ fontFamily: mono, fontSize: 10, color: "var(--color-text-faint)", marginTop: 4 }}>
          {FEATURE_PUBLIC_GRAPHS
            ? `${MODES.find((m) => m.value === effectiveMode)?.desc}; inherited by every node in this graph`
            : "owner and explicit collaborators only; inherited by every node in this graph"}
        </p>
      </div>

      {/* Collaborators */}
      <div>
        <p style={lbl}>collaborators</p>
        {sharingInfo.collaborators.length === 0 ? (
          <p style={{ fontFamily: mono, fontSize: 11, color: "var(--color-text-faint)", margin: 0 }}>
            no collaborators added yet
          </p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {sharingInfo.collaborators.map((c) => (
              <div key={c.email} style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "5px 8px", borderRadius: 2,
                border: "1px solid var(--color-border)",
              }}>
                <div>
                  <span style={{ fontFamily: mono, fontSize: 11, color: "var(--color-text)" }}>{c.email}</span>
                  <span style={{ fontFamily: mono, fontSize: 10, color: "var(--color-text-faint)", marginLeft: 6 }}>
                    {isFrozen ? "viewer (frozen)" : c.role}
                  </span>
                </div>
                {canManage && (
                  <button
                    onClick={() => onRemoveCollaborator?.(c.email)}
                    aria-label={`remove ${c.email}`}
                    style={{ width: 44, height: 44, display: "inline-grid", placeItems: "center", background: "none", border: "none", cursor: "pointer", color: "var(--color-text-faint)", padding: 0 }}
                    title="remove collaborator"
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add form */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, opacity: mutationUnavailable ? 0.55 : 1 }}>
        <input
          className="sharing-field"
          type="email"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
          placeholder={!canManage
            ? "admin access required"
            : collaborationUnavailable
              ? "collaboration coming soon"
              : "email"}
          onKeyDown={(e) => e.key === "Enter" && !mutationUnavailable && handleAdd()}
          disabled={mutationUnavailable}
          style={{ ...input, flex: 1, minWidth: 0 }}
        />
        <select
          className="sharing-field"
          value={newRole}
          onChange={(e) => setNewRole(e.target.value as Collaborator["role"])}
          disabled={mutationUnavailable}
          style={input}
        >
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <button
          className="sharing-field"
          onClick={handleAdd}
          disabled={!newEmail.trim() || mutationUnavailable}
          title={!canManage
            ? "Administrator access is required"
            : collaborationUnavailable
              ? "Private collaboration is coming soon"
              : undefined}
          style={{
            ...input,
            cursor: newEmail.trim() && !mutationUnavailable ? "pointer" : "not-allowed",
            background: "var(--color-bg-elevated)",
            opacity: newEmail.trim() && !mutationUnavailable ? 1 : 0.4,
          }}
        >
          add
        </button>
      </div>

      {/* Permissions */}
      <div>
        <p style={lbl}>your permissions</p>
        <div style={{ display: "flex", gap: 6 }}>
          {(["View", "Write", "Admin"] as const).map((p) => {
            const on = p === "View" ? sharingInfo.effective.can_view
              : p === "Write" ? sharingInfo.effective.can_write
              : sharingInfo.effective.can_admin;
            return (
              <span key={p} style={{
                fontFamily: mono, fontSize: 10, fontWeight: 500,
                padding: "2px 8px", borderRadius: 2,
                background: on ? "var(--color-accent-subtle)" : "var(--color-bg-elevated)",
                color: on ? "var(--color-text)" : "var(--color-text-faint)",
              }}>
                {on && "✓ "}{p.toLowerCase()}
              </span>
            );
          })}
        </div>
      </div>

      {/* Owner */}
      <p style={{ fontFamily: mono, fontSize: 10, color: "var(--color-text-faint)", margin: 0 }}>
        owned by {sharingInfo.owner_email}
        {sharingInfo.is_owner && <span style={{ color: "var(--color-text-muted)" }}> (you)</span>}
      </p>
      <style>{`
        .sharing-field:focus-visible {
          outline: 2px solid var(--color-border-strong);
          outline-offset: 2px;
        }
        @media (max-width: 720px) {
          .sharing-panel input,
          .sharing-panel select { font-size: 16px !important; }
        }
      `}</style>
    </div>
  );
}
