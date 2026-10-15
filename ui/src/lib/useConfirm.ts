import { atlasUIHost } from "../runtime.js";
import { useUIStore } from "../stores/uiStore.js";

interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmVariant?: "primary" | "danger";
}

export function useConfirm() {
  const callback = atlasUIHost().useConfirm;
  if (callback) return callback();
  const setConfirmRequest = useUIStore((s) => s.setConfirmRequest);

  return (opts: ConfirmOptions): Promise<boolean> =>
    new Promise((resolve) => {
      setConfirmRequest({ ...opts, resolve });
    });
}
