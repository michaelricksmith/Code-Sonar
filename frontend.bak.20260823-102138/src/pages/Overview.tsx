import { useMemo } from "react";
import { useScan } from "@/state/useScan";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { ScoreChangeCallout } from "@/components/ScoreChangeCallout";
import { CategoryBreakdownChart } from "@/components/CategoryBreakdownChart";
import { cn, gradeColor } from "@/lib/utils";

const ANALYZER_COUNT = 8;

export function OverviewPage() {
  const { scanResult, scanning, hasScan, driftResult, history } = useScan();

  if (scanning) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-10 w-32 mt-2" />
            </CardHeader>
          </Card>
        ))}
      </div>
    );
  }

  if (!hasScan || !scanResult) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No scan yet</CardTitle>
          <CardDescription>
            Enter a repository path above and click Run scan to compute the
            risk score. The dashboard will populate with findings, hotspots,
            category breakdown, and historical drift.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-2">
          <p>
            <span className="font-semibold">Tip:</span> scan the bundled demo
            repo at <span className="font-mono">demo/sample_repo/state-A</span>{" "}
            to see a populated dashboard.
          </p>
          <Separator />
          <p>
            Past scans for any repository: {history.length}.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="uppercase tracking-wider text-[11px]">
              Score
            </CardDescription>
            <CardTitle
              className={cn(
                "text-5xl font-semibold tabular-nums",
                gradeColor(scanResult.grade)
              )}
            >
              {scanResult.score}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Badge variant="outline" className="font-mono">
              Grade {scanResult.grade}
            </Badge>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="uppercase tracking-wider text-[11px]">
              Findings
            </CardDescription>
            <CardTitle className="text-5xl font-semibold tabular-nums">
              {scanResult.finding_count}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Across all analyzers
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="uppercase tracking-wider text-[11px]">
              Total debt
            </CardDescription>
            <CardTitle className="text-5xl font-semibold tabular-nums">
              {scanResult.total_debt_points}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Severity-weighted points
          </CardContent>
        </Card>
      </div>

      <ScoreChangeCallout
        result={scanResult}
        analyzerCount={ANALYZER_COUNT}
      />

      <Card>
        <CardHeader>
          <CardTitle>Category breakdown</CardTitle>
          <CardDescription>
            How the score is composed across complexity, security, staleness, maintainability, and testing.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <CategoryBreakdownChart findingsByCategory={scanResult.findings_by_category} />
        </CardContent>
      </Card>

      {driftResult && (
        <Card>
          <CardHeader>
            <CardTitle>Last drift summary</CardTitle>
            <CardDescription>
              Δ score {driftResult.summary.score_delta >= 0 ? "+" : ""}
              {driftResult.summary.score_delta} · Δ debt{" "}
              {driftResult.summary.debt_delta >= 0 ? "+" : ""}
              {driftResult.summary.debt_delta} · Δ findings{" "}
              {driftResult.summary.finding_delta >= 0 ? "+" : ""}
              {driftResult.summary.finding_delta}
            </CardDescription>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Open the Drift page for full breakdown.
          </CardContent>
        </Card>
      )}
    </div>
  );
}