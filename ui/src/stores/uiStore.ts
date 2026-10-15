import { create } from "zustand";

type SidePanelKind = "detail" | "sharing" | "tags" | "artifacts" | null;

export interface Toast {
  id: string;
  type: "error" | "success" | "info";
  message: string;
}

export interface ConfirmRequest {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmVariant?: "primary" | "danger";
  resolve: (value: boolean) => void;
}

interface UIState {
  sidePanel: SidePanelKind;
  toasts: Toast[];
  confirmRequest: ConfirmRequest | null;

  setSidePanel: (panel: SidePanelKind) => void;
  closeSidePanel: () => void;
  addToast: (toast: Omit<Toast, "id">) => void;
  removeToast: (id: string) => void;
  setConfirmRequest: (req: ConfirmRequest | null) => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidePanel: null,
  toasts: [],
  confirmRequest: null,

  setSidePanel: (panel: SidePanelKind) => {
    set({ sidePanel: panel });
  },

  closeSidePanel: () => {
    set({ sidePanel: null });
  },

  addToast: (toast) => {
    const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    set((state) => ({ toasts: [...state.toasts, { ...toast, id }] }));
    setTimeout(() => {
      set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
    }, 5000);
  },

  removeToast: (id) => {
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },

  setConfirmRequest: (req) => set({ confirmRequest: req }),
}));
