interface LoadingSpinnerProps {
  size?: number;
  label?: string;
  inline?: boolean;
}

export function LoadingSpinner({
  size = 20,
  label = "Loading",
  inline = false,
}: LoadingSpinnerProps) {
  const svg = (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      role="status"
      aria-label={label}
      style={{ animation: "spinner-rotate 0.8s linear infinite" }}
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
      <style>{`@keyframes spinner-rotate { to { transform: rotate(360deg); } }`}</style>
    </svg>
  );

  if (inline) return svg;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: 120,
        color: "var(--color-text-muted)",
      }}
    >
      {svg}
    </div>
  );
}
