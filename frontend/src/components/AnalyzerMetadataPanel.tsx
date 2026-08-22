// Code Sonar — analyzer registry metadata panel.

import { useEffect, useState } from "react";

import { fetchAnalyzers } from "../api/analyzers";
import type { AnalyzerMetadata } from "../api/analyzers";

interface AnalyzerMetadataPanelProps {
  refreshKey?: number;
}

export function AnalyzerMetadataPanel({
  refreshKey,
}: AnalyzerMetadataPanelProps) {
  const [analyzers, setAnalyzers] = useState<AnalyzerMetadata[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAnalyzers()
      .then((data) => {
        if (!cancelled) {
          setAnalyzers(data);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-800/40 p-6">
      <h2 className="text-lg font-semibold mb-4">Analyzers</h2>
      {error && (
        <p className="text-sm text-rose-300">
          Could not load analyzer registry: {error}
        </p>
      )}
      {!error && analyzers.length === 0 && (
        <p className="text-sm text-slate-400">No analyzers registered.</p>
      )}
      {!error && analyzers.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-slate-800">
          <table className="w-full border-collapse text-sm">
            <thead className="bg-slate-800/60 text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2 text-left">Name</th>
                <th className="px-3 py-2 text-left">Category</th>
                <th className="px-3 py-2 text-right">Threshold</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {analyzers.map((a) => (
                <tr key={a.analyzer_id} className="bg-slate-900/40">
                  <td className="px-3 py-2 font-mono text-xs text-slate-200">
                    {a.analyzer_id}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-300">
                    {a.category}
                  </td>
                  <td className="px-3 py-2 text-right text-xs text-slate-300">
                    {a.threshold ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
