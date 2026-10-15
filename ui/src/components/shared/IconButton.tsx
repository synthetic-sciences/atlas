import type { ButtonHTMLAttributes, ReactNode } from "react";
import { ICON_SIZE } from "../../styles/tokens.js";

type Size = keyof typeof ICON_SIZE;

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  icon: ReactNode;
  label: string;
  size?: Size;
  variant?: "default" | "subtle";
}

export function IconButton({
  icon,
  label,
  size = "lg",
  variant = "default",
  style,
  className,
  ...rest
}: IconButtonProps) {
  const px = ICON_SIZE[size];
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      // `.icon-button` grows to a 44px target on coarse pointers (index.css).
      className={className ? `icon-button ${className}` : "icon-button"}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: px + 16,
        height: px + 16,
        padding: 0,
        background: variant === "subtle" ? "transparent" : "var(--color-accent-subtle)",
        border: variant === "subtle" ? "none" : "1px solid var(--color-border)",
        borderRadius: 2,
        color: "var(--color-text-muted)",
        cursor: "pointer",
        ...style,
      }}
      {...rest}
    >
      {icon}
    </button>
  );
}
