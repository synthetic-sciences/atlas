import { BASE_URL } from "../lib/config";
import { atlasUIHost, type ReadOptions } from "../runtime";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function getAuthHeaders(): Promise<HeadersInit> {
  const callback = atlasUIHost().getAuthHeaders;
  return callback ? callback() : { Authorization: "Bearer local" };
}

export const getApiHeadersAsync = getAuthHeaders;

export async function request<T>(path: string, options?: RequestInit, read?: ReadOptions): Promise<T> {
  const callback = atlasUIHost().request;
  if (callback) {
    if (read !== undefined) return callback<T>(path, options, read);
    return options === undefined ? callback<T>(path) : callback<T>(path, options);
  }
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...Object.fromEntries(new Headers(await getAuthHeaders())), ...Object.fromEntries(new Headers(options?.headers)) },
  });
  if (!response.ok) throw new ApiError(response.status, `Graph request failed (${response.status})`);
  return response.status === 204 ? undefined as T : response.json();
}

export async function publicRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const callback = atlasUIHost().publicRequest;
  if (callback) return options === undefined ? callback<T>(path) : callback<T>(path, options);
  const response = await fetch(`${BASE_URL}${path}`, options);
  if (!response.ok) throw new ApiError(response.status, `Graph request failed (${response.status})`);
  return response.json();
}

export function qs(params: Record<string, string | number | boolean | null | undefined> | undefined): string {
  if (!params) return "";
  const entries = Object.entries(params).filter((entry) => entry[1] != null);
  return entries.length ? `?${new URLSearchParams(entries.map(([key, value]) => [key, String(value)]))}` : "";
}

export { BASE_URL };

