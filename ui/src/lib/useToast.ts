import { atlasUIHost } from "../runtime";
import { useUIStore } from "../stores/uiStore";

export function useToast() {
  const callback = atlasUIHost().useToast;
  if (callback) return callback();
  const addToast = useUIStore((s) => s.addToast);
  return {
    success: (message: string) => addToast({ type: "success", message }),
    error: (message: string) => addToast({ type: "error", message }),
    info: (message: string) => addToast({ type: "info", message }),
  };
}
