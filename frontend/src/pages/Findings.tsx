import { useMemo, useState } from "react";
import { useScan } from "@/state/useScan";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FilterChips } from "@/components/FilterChips";
import { SortableFindingsTable } from "@/components/SortableFindingsTable";
import { FindingDetailDrawer } from "@/components/FindingDetailDrawer";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchAnalyzers } from "@/api/analyzers";
import {
  CATEGORIES,
  SEVERITIES,
  type AnalyzerMetadata,
  type Category,
  type FilterState,
  type Finding,
  type Severity,
  type SortState,
} from "@/api/analyzers";

const EMPTY_FILTER: FilterState = {
  severities: new Set<Severity>(),
  categories: new Set<Category>(),
  analyzers: new Set<string>(),
  search: "",
};

function toggleSet<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

export function FindingsPage() {
  const { scanResult, scanning, fileFilter } = useScan();
  const [selected, setSelected] = useState<Finding | null>(null);
  const [filter, setFilter] = useState<FilterState>(EMPTY_FILTER);
  const [sort, setSort] = useState<SortState>({
    key: "severity",
    direction: "desc",
  });
  const [analyzers, setAnalyzers] = useState<AnalyzerMetadata[]>([]);

  // Best-effort load of analyzer metadata for the chip list.
  useMemo(() => {
    fetchAnalyzers().then(setAnalyzers).catch(() => setAnalyzers([]));
  }, []);

  const filtered = useMemo(() => {
    if (!scanResult) return [] as Finding[];
    return scanResult.findings.filter((f) => {
      if (filter.severities.size > 0 && !filter.severities.has(f.severity)) {
        return false;
      }
      if (filter.categories.size > 0 && !filter.categories.has(f.category)) {
        return false;
      }
      if (filter.analyzers.size > 0 && !filter.analyzers.has(f.analyzer)) {
        return false;
      }
      if (filter.search) {
        const q = filter.search.toLowerCase();
        const haystack = [
          f.file_path,
          f.symbol ?? "",
          f.message,
          f.evidence,
          f.analyzer,
        ]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      if (fileFilter && f.file_path !== fileFilter) {
        return false;
      }
      return true;
    });
  }, [scanResult, filter, fileFilter]);

  if (scanning) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-72 mt-2" />
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!scanResult) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No findings yet</CardTitle>
          <CardDescription>
            Run a scan to populate the findings list. Findings are filterable by
            severity, category, analyzer, and free-text search.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle>Findings</CardTitle>
              <CardDescription>
                Every finding from the latest scan, with redacted secret evidence.
              </CardDescription>
            </div>
            <Badge variant="secondary" className="font-mono">
              {filtered.length} / {scanResult.findings.length}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <FilterChips
            findings={scanResult.findings}
            analyzers={analyzers.map((a) => ({
              analyzer_id: a.analyzer_id,
              name: a.name,
              category: a.category as Category,
              threshold: a.threshold,
            }))}
            filter={filter}
            onChange={setFilter}
          />
          <SortableFindingsTable
            findings={filtered}
            onSelect={setSelected}
            sort={sort}
            onSortChange={setSort}
          />
        </CardContent>
      </Card>
      <FindingDetailDrawer finding={selected} onClose={() => setSelected(null)} />
    </div>
  );
}