import { useScan } from "@/state/useScan";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

export function HistoryPage() {
  const { history, refreshHistory, scanning } = useScan();

  if (scanning) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-32" />
        </CardHeader>
        <CardContent className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 pb-3">
        <div>
          <CardTitle>Scan history</CardTitle>
          <CardDescription>
            Past scans persisted to the local history store. Repository-isolated.
          </CardDescription>
        </div>
        <Badge variant="secondary" className="font-mono">
          {history.length} scans
        </Badge>
      </CardHeader>
      <CardContent>
        {history.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No scans recorded yet. Run your first scan from Overview.
          </p>
        ) : (
          <div className="divide-y divide-border">
            {history.map((s, idx) => (
              <div
                key={s.scan_id ?? idx}
                className="flex flex-col md:flex-row md:items-center md:justify-between gap-2 py-3"
              >
                <div className="flex flex-col gap-1">
                  <span className="font-mono text-xs text-muted-foreground">
                    {s.scan_id ?? "unknown"}
                  </span>
                  <span className="text-sm font-medium">
                    {s.repository_id ?? "(unknown repository)"}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-sm">
                  <Badge variant="outline" className="font-mono">
                    score {s.score}
                  </Badge>
                  <Badge variant="outline" className="font-mono">
                    grade {s.grade}
                  </Badge>
                  <span className="text-muted-foreground font-mono text-xs">
                    {new Date(s.scanned_at).toLocaleString()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
        <button
          onClick={refreshHistory}
          className="text-xs text-muted-foreground hover:text-foreground underline mt-4"
        >
          Refresh
        </button>
      </CardContent>
    </Card>
  );
}