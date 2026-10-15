import type { ComponentType, ReactNode } from "react";
import type { nodesApi } from "./api/nodes.js";
import { configureGraphFeatures } from "./lib/config.js";

export interface ReadOptions {
  fresh?: boolean;
  dedupe?: boolean;
  timeoutMs?: number;
  maxAttempts?: number;
  omitOrganizationContext?: boolean;
  cacheTtlMs?: number;
  presentation?: boolean;
  invalidates?: string[];
}

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmVariant?: "primary" | "danger";
}

export interface ToastActions {
  success(message: string): void;
  error(message: string): void;
  info(message: string): void;
}

export interface AtlasUIHost {
  request?<T>(path: string, options?: RequestInit, read?: ReadOptions): Promise<T>;
  publicRequest?<T>(path: string, options?: RequestInit): Promise<T>;
  getAuthHeaders?(): Promise<HeadersInit>;
  api?: typeof nodesApi;
  Shell?: ComponentType<{ children: ReactNode }>;
  useToast?: () => ToastActions;
  useConfirm?: () => (options: ConfirmOptions) => Promise<boolean>;
  publicGraphsEnabled?: boolean;
}

let current: AtlasUIHost = {};

export function configureAtlasUI(host: AtlasUIHost): void {
  current = { ...current, ...host };
  if (host.publicGraphsEnabled !== undefined) configureGraphFeatures(host.publicGraphsEnabled);
}

export function atlasUIHost(): AtlasUIHost {
  return current;
}

