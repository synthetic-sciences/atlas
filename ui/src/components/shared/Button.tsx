import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

const variantClass: Record<Variant, string> = {
  primary: "btn btn-primary",
  secondary: "btn",
  danger: "btn btn-danger",
  ghost: "btn",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  leftIcon,
  rightIcon,
  disabled,
  children,
  className,
  style,
  ...rest
}: ButtonProps) {
  const sizeStyle =
    size === "sm"
      ? { padding: "4px 10px", fontSize: 11 }
      : undefined;

  const ghostStyle =
    variant === "ghost"
      ? { background: "transparent", border: "1px solid transparent" }
      : undefined;

  return (
    <button
      className={`${variantClass[variant]}${className ? ` ${className}` : ""}`}
      disabled={disabled || loading}
      style={{ ...sizeStyle, ...ghostStyle, ...style }}
      {...rest}
    >
      {loading ? <Spinner /> : leftIcon}
      {children}
      {rightIcon}
    </button>
  );
}

function Spinner() {
  return (
    <svg
      width={12}
      height={12}
      viewBox="0 0 24 24"
      fill="none"
      style={{ animation: "spin 0.8s linear infinite" }}
      aria-hidden
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="3"
        strokeDasharray="31.4 31.4"
        strokeLinecap="round"
      />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </svg>
  );
}
