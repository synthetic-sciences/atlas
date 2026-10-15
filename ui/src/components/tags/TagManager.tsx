import { useState } from "react";
import type { GraphTag } from "../../api/types";
import { TagBadge } from "./TagBadge";

interface TagManagerProps {
  /** All tags available on the graph */
  graphTags: GraphTag[];
  /** IDs of tags currently assigned to this node */
  assignedTagIds: string[];
  /** Called when a tag assignment should be toggled */
  onToggleTag?: (tagId: string, assign: boolean) => void;
  /** Called when a new tag should be created */
  onCreateTag?: (tag: { name: string; bg_color: string; text_color: string }) => void;
  /** Called when a tag should be deleted */
  onDeleteTag?: (tagId: string) => void;
}

export function TagManager({
  graphTags,
  assignedTagIds,
  onToggleTag,
  onCreateTag,
  onDeleteTag,
}: TagManagerProps) {
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newBgColor, setNewBgColor] = useState("var(--kind-insight)");
  const [newTextColor, setNewTextColor] = useState("var(--color-bg)");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const assignedSet = new Set(assignedTagIds);

  function handleCreate() {
    if (!newName.trim()) return;
    onCreateTag?.({ name: newName.trim(), bg_color: newBgColor, text_color: newTextColor });
    setNewName("");
    setNewBgColor("var(--kind-insight)");
    setNewTextColor("var(--color-bg)");
    setShowCreateForm(false);
  }

  function handleDelete(tagId: string) {
    onDeleteTag?.(tagId);
    setConfirmDeleteId(null);
  }

  return (
    <div className="space-y-4">
      {/* Section header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-faint)]">
          Labels
        </h2>
        <button
          onClick={() => setShowCreateForm(!showCreateForm)}
          className="rounded-md px-2.5 py-1 text-xs font-medium text-[var(--color-accent)] transition-colors hover:bg-[var(--color-accent-subtle)]"
        >
          {showCreateForm ? "Cancel" : "+ New label"}
        </button>
      </div>

      {/* Create form */}
      {showCreateForm && (
        <div className="space-y-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-subtle)] p-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
              Name
            </label>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Label name"
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-faint)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]"
            />
          </div>

          <div className="flex gap-4">
            <div className="flex-1">
              <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
                Background
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={newBgColor}
                  onChange={(e) => setNewBgColor(e.target.value)}
                  className="h-8 w-8 cursor-pointer rounded border border-[var(--color-border)]"
                />
                <span className="text-xs text-[var(--color-text-faint)]">{newBgColor}</span>
              </div>
            </div>
            <div className="flex-1">
              <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
                Text
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={newTextColor}
                  onChange={(e) => setNewTextColor(e.target.value)}
                  className="h-8 w-8 cursor-pointer rounded border border-[var(--color-border)]"
                />
                <span className="text-xs text-[var(--color-text-faint)]">{newTextColor}</span>
              </div>
            </div>
          </div>

          {/* Preview */}
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
              Preview
            </label>
            <span
              className="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium"
              style={{ backgroundColor: newBgColor, color: newTextColor }}
            >
              {newName || "Label name"}
            </span>
          </div>

          <button
            onClick={handleCreate}
            disabled={!newName.trim()}
            className="rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            Create label
          </button>
        </div>
      )}

      {/* Tag list */}
      {graphTags.length === 0 ? (
        <p className="text-sm text-[var(--color-text-muted)]">
          No labels defined yet. Create one to get started.
        </p>
      ) : (
        <div className="space-y-2">
          {graphTags.map((tag) => {
            const isAssigned = assignedSet.has(tag.tag_id);
            const isConfirmingDelete = confirmDeleteId === tag.tag_id;

            return (
              <div
                key={tag.tag_id}
                className="flex items-center justify-between gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <TagBadge
                    tag={tag}
                    assigned={isAssigned}
                    onClick={() => onToggleTag?.(tag.tag_id, !isAssigned)}
                  />
                  {tag.one_only && (
                    <span className="rounded bg-[var(--color-bg-elevated)] px-1.5 py-0.5 text-[0.65rem] font-medium text-[var(--color-text-faint)]">
                      one_only
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-1">
                  {isConfirmingDelete ? (
                    <>
                      <span className="mr-1 text-xs text-[var(--color-text-muted)]">
                        Delete?
                      </span>
                      <button
                        onClick={() => handleDelete(tag.tag_id)}
                        className="rounded px-2 py-1 text-xs font-medium text-red-500 transition-colors hover:bg-red-500/10"
                      >
                        Yes
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="rounded px-2 py-1 text-xs text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-bg-elevated)]"
                      >
                        No
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => setConfirmDeleteId(tag.tag_id)}
                      className="rounded p-1 text-[var(--color-text-faint)] transition-colors hover:bg-[var(--color-bg-elevated)] hover:text-red-500"
                      title="Delete label"
                    >
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 14 14"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M2.5 4h9M5.5 4V2.5h3V4M5.5 6.5v4M8.5 6.5v4M3.5 4l.5 8h6l.5-8" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
