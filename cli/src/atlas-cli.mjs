import { tryRuntimeCommand } from "./atlas-runtime/dispatch.mjs";

export async function run(argv = process.argv) {
  const handled = await tryRuntimeCommand(argv);
  if (handled) return handled === true ? 0 : handled;
  throw new Error("legacy setup commands are not part of the Gateway core CLI package");
}
