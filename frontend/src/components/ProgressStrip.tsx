import { useEffect, useState } from "react";

interface FixStats {
  total_verified: number;
  verified_this_week: number;
  best_week: { week_start: string; count: number } | null;
  in_progress: number;
  streak: { current_streak_weeks: number; longest_streak_weeks: number };
}

interface Nudge {
  signal: string;
  text: string;
}

export function ProgressStrip() {
  const [stats, setStats] = useState<FixStats | null>(null);
  const [nudge, setNudge] = useState<Nudge | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/fix-tracking/stats", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data) setStats(data);
      })
      .catch(() => {});
    fetch("/api/retention/nudge", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data?.nudge) setNudge(data.nudge);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!stats && !nudge) return null;

  return (
    <div>
      {nudge && (
        <div className="notice warning" style={{ marginBottom: 14 }}>
          {nudge.text}
        </div>
      )}
      {stats && (stats.total_verified > 0 || stats.in_progress > 0) && (
        <section className="card" style={{ marginBottom: 14 }}>
          <div className="lbl">Your progress</div>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginTop: 8 }}>
            <div>
              <div style={{ fontSize: 22, fontWeight: 700 }}>{stats.total_verified}</div>
              <div className="lbl">fixes verified</div>
            </div>
            <div>
              <div style={{ fontSize: 22, fontWeight: 700 }}>{stats.verified_this_week}</div>
              <div className="lbl">this week</div>
            </div>
            {stats.streak.current_streak_weeks > 1 && (
              <div>
                <div style={{ fontSize: 22, fontWeight: 700 }}>
                  {stats.streak.current_streak_weeks} 🔥
                </div>
                <div className="lbl">week streak</div>
              </div>
            )}
            {stats.in_progress > 0 && (
              <div>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{stats.in_progress}</div>
                <div className="lbl">in progress</div>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
