import { nodesApi } from "./nodes.js";
import { atlasUIHost } from "../runtime.js";

export { ApiError, getApiHeadersAsync } from "./internal.js";

export const api: typeof nodesApi = new Proxy(nodesApi, {
  get(target, key) {
    return Reflect.get(atlasUIHost().api ?? target, key);
  },
});

