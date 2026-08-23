import { useScan } from "@/state/useScan";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { DriftView } from "@/components/DriftView";
import { GitCompare } from "lucide-react";

export function DriftPage() {
  const { repoPath, driftResult, comparePrevious, scanning } = useScan();

  if (scanning) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!driftResult) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No drift yet</CardTitle>
          <CardDescription>
            Compare the latest scan against the previous one for this repository.
            Requires at least two scans.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={comparePrevious} disabled={!repoPath.trim()}>
            <GitCompare className="h-4 w-4" />
            Compute drift
          </Button>
          {repoPath.trim() && (
            <p className="text-xs text-muted-foreground mt-3 font-mono">
              {repoPath}
            </p>
          )}
          <div className="mt-4">
            <Badge variant="outline" className="text-xs">
              Need at least two scans to compute drift.
            </Badge>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Drift since previous scan</h2>
          <p className="text-xs text-muted-foreground font-mono">{repoPath}</p>
        </div>
        <Button variant="outline" onClick={comparePrevious}>
          <GitCompare className="h-4 w-4" />
          Recompute
        </Button>
      </div>
      <DriftView drift={driftResult} />
    </div>
  );
}