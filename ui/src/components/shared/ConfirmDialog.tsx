import { useUIStore } from "../../stores/uiStore.js";
import { Modal } from "./Modal.js";
import { Button } from "./Button.js";
import { FONT_SANS } from "../../styles/tokens.js";

export function ConfirmDialog() {
  const req = useUIStore((s) => s.confirmRequest);
  const setReq = useUIStore((s) => s.setConfirmRequest);

  if (!req) return null;

  const cancel = () => {
    req.resolve(false);
    setReq(null);
  };
  const confirm = () => {
    req.resolve(true);
    setReq(null);
  };
  // A stray Enter right after opening must not run an irreversible action:
  // destructive confirmations start on Cancel.
  const destructive = req.confirmVariant === "danger";

  return (
    <Modal open={true} onClose={cancel} title={req.title} maxWidth={420}>
      <div
        style={{
          padding: "16px 18px 18px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
          fontFamily: FONT_SANS,
        }}
      >
        {req.message && (
          <p
            style={{
              margin: 0,
              fontSize: 12,
              lineHeight: 1.6,
              color: "var(--color-text-muted)",
            }}
          >
            {req.message}
          </p>
        )}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
          }}
        >
          <Button variant="secondary" onClick={cancel} autoFocus={destructive}>
            {req.cancelLabel || "Cancel"}
          </Button>
          <Button
            variant={destructive ? "danger" : "primary"}
            onClick={confirm}
            autoFocus={!destructive}
          >
            {req.confirmLabel || "Confirm"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
