import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  History,
  Settings as SettingsIcon,
  LayoutDashboard,
  Search,
  ScanLine,
  ListChecks,
  Flame,
  GitCompare,
} from "lucide-react";
import {
  BrowserRouter,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useScan } from "@/state/useScan";
import { useDrift } from "@/state/useDrift";
import { OverviewPage } from "@/pages/Overview";
import { FindingsPage } from "@/pages/Findings";
import { RiskHotspotsPage } from "@/pages/RiskHotspots";
import { HistoryPage } from "@/pages/History";
import { DriftPage } from "@/pages/Drift";
import { SettingsPage } from "@/pages/Settings";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/findings", label: "Findings", icon: ListChecks },
  { to: "/hotspots", label: "Risk Hotspots", icon: Flame },
  { to: "/history", label: "History", icon: History },
  { to: "/drift", label: "Drift", icon: GitCompare },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

function Brand() {
  return (
    <div className="flex items-center gap-2 select-none">
      <div className="h-8 w-8 rounded-md bg-sonar-steel text-white grid place-items-center font-semibold tracking-tight">
        CS
      </div>
      <div className="flex flex-col leading-tight">
        <span className="text-base font-semibold tracking-tight text-sonar-graphite">
          Code Sonar
        </span>
        <span className="text-[11px] uppercase tracking-[0.14em] text-sonar-muted">
          Software Risk Intelligence
        </span>
      </div>
    </div>
  );
}

function RepoBar({
  repoPath,
  setRepoPath,
  onScan,
  onCompare,
  scanning,
  hasScan,
  hasHistory,
}: {
  repoPath: string;
  setRepoPath: (v: string) => void;
  onScan: () => void;
  onCompare: () => void;
  scanning: boolean;
  hasScan: boolean;
  hasHistory: boolean;
}) {
  return (
    <Card className="border-sonar-border shadow-none">
      <CardContent className="p-4 flex flex-col gap-3 md:flex-row md:items-end">
        <div className="flex-1">
          <Label htmlFor="repo-path" className="text-xs uppercase tracking-wider text-sonar-muted">
            Repository path
          </Label>
          <div className="relative mt-1.5">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-sonar-muted" />
            <Input
              id="repo-path"
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              placeholder="C:\path\to\repository"
              className="pl-9 font-mono text-sm"
              spellCheck={false}
              autoComplete="off"
            />
          </div>
        </div>
        <div className="flex gap-2">
          <TooltipProvider delayDuration={150}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="default"
                  onClick={onScan}
                  disabled={scanning || !repoPath.trim()}
                >
                  <ScanLine className="h-4 w-4" />
                  {scanning ? "Scanning…" : "Run scan"}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Scan a repository and compute its risk score.</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <Button
            variant="outline"
            onClick={onCompare}
            disabled={!hasScan || !hasHistory}
          >
            <GitCompare className="h-4 w-4" />
            Compare with previous
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Sidebar() {
  return (
    <aside className="hidden md:flex md:w-60 md:flex-col md:border-r md:border-sonar-border md:bg-card">
      <div className="px-5 py-5 border-b border-sonar-border">
        <Brand />
      </div>
      <ScrollArea className="flex-1 px-3 py-4">
        <nav className="flex flex-col gap-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-sonar-steel/10 text-sonar-steel"
                    : "text-sonar-graphite hover:bg-muted"
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </ScrollArea>
      <div className="border-t border-sonar-border px-5 py-4 text-[11px] uppercase tracking-[0.14em] text-sonar-muted">
        v0.1.0-beta.1 · private
      </div>
    </aside>
  );
}

function PageHeader({ title, subtitle, badge }: { title: string; subtitle?: string; badge?: string }) {
  return (
    <div className="flex items-start justify-between gap-4 pb-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-sonar-graphite">{title}</h1>
        {subtitle && <p className="text-sm text-sonar-muted mt-1">{subtitle}</p>}
      </div>
      {badge && <Badge variant="secondary">{badge}</Badge>}
    </div>
  );
}

export function AppShell() {
  const location = useLocation();
  const {
    repoPath,
    setRepoPath,
    scanResult,
    scanning,
    error,
    history,
    refreshHistory,
    runScan,
    comparePrevious,
    driftResult,
    hasScan,
    hasHistory,
  } = useScan();

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  const pageMeta = useMemo(() => {
    const map: Record<string, { title: string; subtitle?: string; badge?: string }> = {
      "/": { title: "Overview", subtitle: "Risk score, summary, and live deltas.", badge: scanResult?.scan_id ? `Scan ${scanResult.scan_id.slice(0, 8)}` : undefined },
      "/findings": { title: "Findings", subtitle: "Every finding from the latest scan, with filters.", badge: scanResult ? `${scanResult.finding_count} findings` : undefined },
      "/hotspots": { title: "Risk Hotspots", subtitle: "Files ranked by deterministic risk score.", badge: scanResult ? `Top ${Math.min(scanResult.top_hotspots?.length ?? 0, 10)}` : undefined },
      "/history": { title: "History", subtitle: "Past scans for this repository.", badge: history.length > 0 ? `${history.length} scans` : undefined },
      "/drift": { title: "Drift", subtitle: "What changed since the previous scan.", badge: driftResult ? `Δ ${driftResult.summary.score_delta >= 0 ? "+" : ""}${driftResult.summary.score_delta}` : undefined },
      "/settings": { title: "Settings", subtitle: "Analyzers, scoring, and storage." },
    };
    return map[location.pathname] ?? { title: "Code Sonar" };
  }, [location.pathname, scanResult, history.length, driftResult]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="flex">
        <Sidebar />
        <div className="flex-1 min-w-0 flex flex-col">
          <header className="sticky top-0 z-30 border-b border-sonar-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
            <div className="px-6 py-4 flex items-center gap-4">
              <div className="md:hidden">
                <Brand />
              </div>
              <div className="hidden md:flex items-center gap-2 text-xs text-sonar-muted">
                <Activity className="h-3.5 w-3.5" />
                <span>Software Risk Intelligence</span>
                <Separator orientation="vertical" className="mx-2 h-4" />
                <span>Credit report for your codebase</span>
              </div>
              <div className="ml-auto flex items-center gap-2">
                <Badge variant="outline" className="font-mono text-[11px]">
                  v0.1.0-beta.1
                </Badge>
              </div>
            </div>
          </header>
          <main className="flex-1 px-6 py-6 space-y-6 max-w-[1400px] w-full mx-auto">
            <PageHeader
              title={pageMeta.title}
              subtitle={pageMeta.subtitle}
              badge={pageMeta.badge}
            />
            {location.pathname === "/" && (
              <RepoBar
                repoPath={repoPath}
                setRepoPath={setRepoPath}
                onScan={runScan}
                onCompare={comparePrevious}
                scanning={scanning}
                hasScan={hasScan}
                hasHistory={hasHistory}
              />
            )}
            {error && (
              <Card className="border-destructive/30 bg-destructive/5">
                <CardHeader className="pb-2">
                  <CardTitle className="text-destructive text-sm">Scan error</CardTitle>
                  <CardDescription className="font-mono text-xs">{error}</CardDescription>
                </CardHeader>
              </Card>
            )}
            <Routes>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/findings" element={<FindingsPage />} />
              <Route path="/hotspots" element={<RiskHotspotsPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/drift" element={<DriftPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </main>
          <footer className="border-t border-sonar-border px-6 py-4 text-[11px] uppercase tracking-[0.14em] text-sonar-muted">
            Code Sonar · deterministic · local-only · v0.1.0-beta.1
          </footer>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}

// Keep TabsContent exported via the import above (consumed by page modules).
export { Tabs, TabsList, TabsTrigger, TabsContent };