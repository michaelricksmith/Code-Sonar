/**
 * NerdsDetails — "Details for nerds" collapsible (§2.7).
 * Raw metadata, analyzer names, scan ids and evidence live here:
 * one click away, never the first thing.
 */

import type { ReactNode } from "react";

interface NerdsDetailsProps {
  title?: string;
  children: ReactNode;
}

export function NerdsDetails({ title = "Details for nerds", children }: NerdsDetailsProps) {
  return (
    <details className="nerds">
      <summary>
        <span className="chev">▸</span>
        {title}
      </summary>
      <div className="nerds-body">{children}</div>
    </details>
  );
}
