import { nodesApi } from "./nodes";
import { atlasUIHost } from "../runtime";

export { ApiError, getApiHeadersAsync } from "./internal";

export const api: typeof nodesApi = new Proxy(nodesApi, {
  get(target, key) {
    return Reflect.get(atlasUIHost().api ?? target, key);
  },
});

