/**
 * IssuesView — the full ranked issue list ("View all N issues").
 */

import { useMemo, useState } from "react";

import type { Finding, ScanResponse, Severity } from "../api/analyzers";
import { SEVERITY_LABEL, copy } from "../copy";
import { IssueCard } from "./Dashboard";
import { rankIssues } from "../copy/issues";

interface IssuesViewProps {
  result: ScanResponse;
  onOpenIssue: (finding: Finding) => void;
}

const FILTERS: Array<{ id: Severity | "all"; label: string }> = [
  { id: "all", label: "All" },
  { id: "critical", label: SEVERITY_LABEL.critical },
  { id: "error", label: SEVERITY_LABEL.error },
  { id: "warning", label: SEVERITY_LABEL.warning },
  { id: "info", label: SEVERITY_LABEL.info },
];

export function IssuesView({ result, onOpenIssue }: IssuesViewProps) {
  const [filter, setFilter] = useState<Severity | "all">("all");
  const [search, setSearch] = useState("");

  const ranked = useMemo(() => rankIssues(result.findings), [result]);
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return ranked.filter((f) => {
      if (filter !== "all" && f.severity !== filter) return false;
      if (!needle) return true;
      return [f.file_path, f.message, f.symbol ?? ""].some((v) => v.toLowerCase().includes(needle));
    });
  }, [ranked, filter, search]);

  return (
    <div className="page">
      <div className="topbar">
        <div className="crumb">
          Projects / <b>{result.repository}</b> / Issues
        </div>
      </div>

      <h1 className="page-title">Issues</h1>
      <p className="page-sub">
        Ranked by impact — the top of this list is where your score goes to recover.
      </p>

      <div style={{ display: "flex", gap: 10, marginTop: 22, flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {FILTERS.map((f) => (
            <button
              key={f.id}
              className={`suggest ${filter === f.id ? "" : ""}`}
              style={filter === f.id ? { background: "var(--teal)", color: "#fff", borderColor: "var(--teal)" } : undefined}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          className="search-input"
          style={{ maxWidth: 280, marginLeft: "auto" }}
          placeholder="Search files or issues…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search issues"
        />
      </div>

      <div style={{ marginTop: 20 }}>
        {visible.length === 0 && (
          <div className="empty-panel">
            {result.finding_count === 0
              ? `No ${copy.findings} found — your code is clean. 🎉`
              : `Nothing matches. Try a different filter.`}
          </div>
        )}
        {visible.map((finding) => (
          <IssueCard key={finding.id} finding={finding} onOpen={onOpenIssue} />
        ))}
      </div>
    </div>
  );
}
