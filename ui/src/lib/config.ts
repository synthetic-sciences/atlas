export const BASE_URL = "/api";
export let FEATURE_PUBLIC_GRAPHS = false;

export function configureGraphFeatures(publicGraphsEnabled: boolean): void {
  FEATURE_PUBLIC_GRAPHS = publicGraphsEnabled;
}

