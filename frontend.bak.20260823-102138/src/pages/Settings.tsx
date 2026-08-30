import { useEffect, useState } from "react";
import axios from "axios";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

type Analyzer = {
  id: string;
  name: string;
  category: string;
  description: string;
  default_severity?: string;
};

export function SettingsPage() {
  const [analyzers, setAnalyzers] = useState<Analyzer[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    axios
      .get<Analyzer[]>("/api/analyzers")
      .then((r) => setAnalyzers(r.data))
      .catch((e) => setError(String(e?.message ?? e)));
  }, []);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Analyzers</CardTitle>
          <CardDescription>
            Active analyzers registered for this build. {analyzers.length} total.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error && (
            <p className="text-sm text-destructive font-mono mb-3">{error}</p>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {analyzers.map((a) => (
              <div
                key={a.id}
                className="rounded-md border border-border p-3 flex flex-col gap-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-sm font-semibold">
                    {a.id}
                  </span>
                  <Badge variant="outline" className="text-[10px] uppercase tracking-wider">
                    {a.category}
                  </Badge>
                </div>
                <span className="text-xs text-muted-foreground">
                  {a.name}
                </span>
                <span className="text-xs">{a.description}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Storage</CardTitle>
          <CardDescription>
            Scan history is persisted to the local JSONL store at{" "}
            <span className="font-mono">~/.code-sonar/history.jsonl</span>.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm space-y-2">
          <p>
            Atomic writes via <code className="font-mono">os.replace</code>.
            Repository-isolated. Schema-versioned.
          </p>
          <Separator />
          <p className="text-xs text-muted-foreground">
            Secret evidence is redacted on the way to disk and on the way to
            the UI. Code Sonar reports uncomfortable results when the evidence
            supports them.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}