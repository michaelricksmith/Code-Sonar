import { useMemo, useState } from "react";
import { useScan } from "@/state/useScan";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { RiskHotspots } from "@/components/RiskHotspots";
import { FindingDetailDrawer } from "@/components/FindingDetailDrawer";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchHotspots } from "@/api/analyzers";
import type { Finding, HotspotResult } from "@/api/analyzers";

export function RiskHotspotsPage() {
  const { scanResult, scanning, repoPath, setFileFilter, fileFilter } = useScan();
  const [selected, setSelected] = useState<Finding | null>(null);
  const [hotspotResult, setHotspotResult] = useState<HotspotResult | null>(null);

  useMemo(() => {
    if (!repoPath.trim()) return;
    fetchHotspots(repoPath.trim(), 10)
      .then(setHotspotResult)
      .catch(() => setHotspotResult(null));
  }, [repoPath, scanResult]);

  if (scanning) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-4 w-72 mt-2" />
        </CardHeader>
        <CardContent className="space-y-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }

  if (!scanResult) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No hotspots yet</CardTitle>
          <CardDescription>
            Run a scan to see the top risk hotspots. Hotspots combine per-file
            debt, severity, finding count, and analyzer diversity.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const hotspots = hotspotResult?.hotspots ?? scanResult.top_hotspots ?? [];
  const summary = hotspotResult ?? {
    hotspots,
    total_files: 0,
    files_with_findings: hotspots.length,
    total_findings: scanResult.finding_count,
    total_debt: scanResult.total_debt_points,
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Risk Hotspots</CardTitle>
          <CardDescription>
            Top {hotspots.length} ranked by deterministic per-file risk score. Click a hotspot
            to filter findings below.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RiskHotspots
            hotspots={hotspots}
            hotspotSummary={{
              total_files: summary.total_files,
              files_with_findings: summary.files_with_findings,
              total_findings: summary.total_findings,
              total_debt: summary.total_debt,
            }}
            findings={scanResult.findings}
            onFilterByFile={(f) => setFileFilter(f)}
            activeFileFilter={fileFilter ?? null}
          />
        </CardContent>
      </Card>
      <FindingDetailDrawer finding={selected} onClose={() => setSelected(null)} />
    </div>
  );
}