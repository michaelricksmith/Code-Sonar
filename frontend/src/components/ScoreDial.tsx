/**
 * ScoreDial — the sonar score arc. Semicircle gauge: red (300) on the left
 * through amber to green (850) on the right, matching the mockups.
 */

interface ScoreDialProps {
  score: number;
  /** width in px; the viewBox scales proportionally */
  width?: number;
  /** animate the fill when the score changes */
  animate?: boolean;
  id?: string;
}

function clampScore(score: number): number {
  if (Number.isNaN(score)) return 300;
  return Math.max(300, Math.min(850, score));
}

export function ScoreDial({ score, width = 240, animate = true, id = "scoreGrad" }: ScoreDialProps) {
  const s = clampScore(score);
  const frac = (s - 300) / 550;
  const ARC_LEN = 314.16;
  const offset = ARC_LEN * (1 - frac);
  // Needle dot at angle θ measured from the left end of the arc.
  const theta = Math.PI * (1 - frac);
  const cx = 120 + 100 * Math.cos(theta);
  const cy = 135 - 100 * Math.sin(theta);

  return (
    <svg className="dial" width={width} height={width * 0.625} viewBox="0 0 240 150" role="img" aria-label={`Score ${s} out of 850`}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#DC2626" />
          <stop offset="50%" stopColor="#D97706" />
          <stop offset="100%" stopColor="#16A34A" />
        </linearGradient>
      </defs>
      <path d="M 20 135 A 100 100 0 0 1 220 135" fill="none" className="dial-track" strokeWidth="20" strokeLinecap="round" />
      <path
        d="M 20 135 A 100 100 0 0 1 220 135"
        fill="none"
        stroke={`url(#${id})`}
        strokeWidth="20"
        strokeLinecap="round"
        strokeDasharray={ARC_LEN}
        strokeDashoffset={offset}
        style={animate ? { transition: "stroke-dashoffset 1s ease" } : undefined}
      />
      <circle cx={cx} cy={cy} r="7" fill="#141A23" />
    </svg>
  );
}
