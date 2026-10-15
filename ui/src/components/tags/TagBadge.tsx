import type { GraphTag } from "../../api/types";

interface TagBadgeProps {
  tag: GraphTag;
  /** Whether this tag is currently assigned to the node */
  assigned?: boolean;
  onClick?: () => void;
}

export function TagBadge({ tag, assigned = false, onClick }: TagBadgeProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-opacity hover:opacity-80"
      style={{
        backgroundColor: tag.bg_color,
        color: tag.text_color,
      }}
    >
      {/* Checkmark for assigned tags */}
      {assigned && (
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M2.5 6.5 5 9l4.5-6" />
        </svg>
      )}

      {tag.name}

      {/* one_only indicator */}
      {tag.one_only && (
        <sup className="ml-0.5 text-[0.6rem] font-bold leading-none opacity-70">1</sup>
      )}
    </button>
  );
}
