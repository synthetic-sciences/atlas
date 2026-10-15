import type { ReactNode } from "react";
import { atlasUIHost } from "../../runtime";

export function Layout({ children }: { children: ReactNode }) {
  const Shell = atlasUIHost().Shell;
  return Shell ? <Shell>{children}</Shell> : <>{children}</>;
}

